from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from openpyxl import Workbook
from sqlalchemy import inspect, text

from models import (
    db,
    Usuario,
    Insumo,
    MovimentacaoEstoque,
    Produto,
    FichaTecnica,
    Venda,
    Financeiro,
)

import io
import os
import shutil
from datetime import datetime


app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "chave-local-altere-em-producao",
)

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///database.db",
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


def criar_banco():
    """Cria as tabelas e acrescenta colunas novas em bancos já existentes."""

    db.create_all()

    inspector = inspect(db.engine)
    tabelas = inspector.get_table_names()

    # ==================================================
    # AJUSTES NA TABELA FICHA_TECNICA
    # ==================================================

    if "ficha_tecnica" in tabelas:
        colunas_ficha = {
            coluna["name"]
            for coluna in inspector.get_columns(
                "ficha_tecnica"
            )
        }

        if "produto_base_id" not in colunas_ficha:
            with db.engine.begin() as conexao:
                conexao.execute(
                    text(
                        """
                        ALTER TABLE ficha_tecnica
                        ADD COLUMN produto_base_id INTEGER
                        REFERENCES produto(id)
                        """
                    )
                )

            print(
                "Coluna produto_base_id criada com sucesso."
            )

    # ==================================================
    # AJUSTES NA TABELA PRODUTO
    # ==================================================

    if "produto" in tabelas:
        colunas_produto = {
            coluna["name"]
            for coluna in inspector.get_columns(
                "produto"
            )
        }

        if "finalidade" not in colunas_produto:
            with db.engine.begin() as conexao:
                conexao.execute(
                    text(
                        """
                        ALTER TABLE produto
                        ADD COLUMN finalidade VARCHAR(30)
                        NOT NULL DEFAULT 'Venda'
                        """
                    )
                )

            print(
                "Coluna finalidade criada com sucesso."
            )

        if (
            "rendimento_quantidade"
            not in colunas_produto
        ):
            with db.engine.begin() as conexao:
                conexao.execute(
                    text(
                        """
                        ALTER TABLE produto
                        ADD COLUMN rendimento_quantidade
                        FLOAT DEFAULT 1
                        """
                    )
                )

            print(
                "Coluna rendimento_quantidade "
                "criada com sucesso."
            )

        if "rendimento_unidade" not in colunas_produto:
            with db.engine.begin() as conexao:
                conexao.execute(
                    text(
                        """
                        ALTER TABLE produto
                        ADD COLUMN rendimento_unidade
                        VARCHAR(20) DEFAULT 'un'
                        """
                    )
                )

            print(
                "Coluna rendimento_unidade "
                "criada com sucesso."
            )

def usuario_logado():
    return "usuario_id" in session


def converter_float(valor, padrao=0.0):
    """Converte campos numéricos aceitando ponto ou vírgula."""
    if valor is None:
        return padrao

    texto_valor = str(valor).strip()

    if not texto_valor:
        return padrao

    try:
        return float(texto_valor.replace(",", "."))
    except ValueError:
        return padrao


def ficha_cria_ciclo(produto_id, produto_base_id, visitados=None):
    """Verifica se a inclusão de um produto-base criaria referência circular."""
    if produto_id == produto_base_id:
        return True

    if visitados is None:
        visitados = set()

    if produto_base_id in visitados:
        return False

    visitados.add(produto_base_id)

    itens_base = FichaTecnica.query.filter_by(
        produto_id=produto_base_id
    ).all()

    for item in itens_base:
        if item.produto_base_id:
            if item.produto_base_id == produto_id:
                return True

            if ficha_cria_ciclo(
                produto_id,
                item.produto_base_id,
                visitados,
            ):
                return True

    return False


def calcular_consumo_insumos(produto, multiplicador=1.0, caminho=None):
    """
    Expande a ficha técnica do produto e retorna uma lista de consumos:
    [(insumo, quantidade_para_baixa), ...].

    Produtos-base são abertos recursivamente até chegar aos insumos.
    """
    if caminho is None:
        caminho = set()

    if produto.id in caminho:
        raise ValueError(
            f"Foi encontrada uma referência circular na ficha de {produto.nome}."
        )

    caminho_atual = set(caminho)
    caminho_atual.add(produto.id)

    consumos = []

    for item in produto.ficha_itens:
        quantidade_item = (
            item.quantidade_convertida_para_estoque()
            * multiplicador
        )

        if item.insumo_id:
            if item.insumo is None:
                raise ValueError(
                    f"Há um insumo inválido na ficha de {produto.nome}."
                )

            consumos.append((item.insumo, quantidade_item))
            continue

        if item.produto_base_id:
            produto_base = Produto.query.get(item.produto_base_id)

            if produto_base is None:
                raise ValueError(
                    f"Há um produto-base inválido na ficha de {produto.nome}."
                )

            consumos.extend(
                calcular_consumo_insumos(
                    produto_base,
                    multiplicador=quantidade_item,
                    caminho=caminho_atual,
                )
            )
            continue

        raise ValueError(
            f"Há um item sem insumo ou produto-base na ficha de {produto.nome}."
        )

    return consumos


with app.app_context():
    criar_banco()


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        nome_usuario = request.form.get("usuario", "").strip()
        senha = request.form.get("senha", "")

        user = Usuario.query.filter_by(
            usuario=nome_usuario
        ).first()

        if user and user.verificar_senha(senha):
            session["usuario_id"] = user.id
            session["usuario_nome"] = user.nome
            return redirect(url_for("dashboard"))

        flash("Usuário ou senha incorretos!")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if not usuario_logado():
        return redirect(url_for("login"))

    insumos_lista = Insumo.query.all()
    produtos_lista = Produto.query.all()
    vendas_lista = Venda.query.all()
    financeiros = Financeiro.query.all()

    receita_vendas = sum(
        venda.receita_total or 0
        for venda in vendas_lista
    )

    cmv_total = sum(
        venda.cmv_total or 0
        for venda in vendas_lista
    )

    margem_total = sum(
        venda.margem_total or 0
        for venda in vendas_lista
    )

    entradas_financeiras = sum(
        financeiro.valor or 0
        for financeiro in financeiros
        if financeiro.tipo == "Entrada"
    )

    despesas_operacionais = sum(
        financeiro.valor or 0
        for financeiro in financeiros
        if financeiro.tipo == "Saída"
    )

    receita_total = receita_vendas + entradas_financeiras
    lucro_operacional = margem_total - despesas_operacionais

    margem_percentual = 0

    if receita_vendas > 0:
        margem_percentual = (
            margem_total / receita_vendas
        ) * 100

    valor_estoque = sum(
        insumo.estoque_atual()
        * insumo.custo_medio_unitario()
        for insumo in insumos_lista
    )

    itens_ponto_pedido = sum(
        1
        for insumo in insumos_lista
        if insumo.status_estoque() == "Ponto de pedido"
    )

    cobertura_baixa = sum(
        1
        for insumo in insumos_lista
        if insumo.status_estoque() == "Cobertura baixa"
    )

    insumos_sem_estoque = [
        insumo
        for insumo in insumos_lista
        if insumo.estoque_atual() <= 0
    ]

    insumos_ponto_pedido = [
        insumo
        for insumo in insumos_lista
        if insumo.status_estoque() == "Ponto de pedido"
    ]

    insumos_cobertura_baixa = [
        insumo
        for insumo in insumos_lista
        if insumo.status_estoque() == "Cobertura baixa"
    ]

    produtos_margem_baixa = [
        produto
        for produto in produtos_lista
        if produto.percentual_margem() < 40
    ]

    return render_template(
        "dashboard.html",
        nome=session.get("usuario_nome"),
        total_insumos=len(insumos_lista),
        total_produtos=len(produtos_lista),
        produtos_ativos=sum(
            1
            for produto in produtos_lista
            if produto.ativo
        ),
        valor_estoque=valor_estoque,
        itens_ponto_pedido=itens_ponto_pedido,
        cobertura_baixa=cobertura_baixa,
        receita_total=receita_total,
        receita_vendas=receita_vendas,
        cmv_total=cmv_total,
        margem_total=margem_total,
        margem_percentual=margem_percentual,
        despesas_operacionais=despesas_operacionais,
        lucro_operacional=lucro_operacional,
        insumos_sem_estoque=insumos_sem_estoque,
        insumos_ponto_pedido=insumos_ponto_pedido,
        insumos_cobertura_baixa=insumos_cobertura_baixa,
        produtos_margem_baixa=produtos_margem_baixa,
    )


@app.route("/insumos", methods=["GET", "POST"])
def insumos():
    if not usuario_logado():
        return redirect(url_for("login"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        unidade = request.form.get("unidade", "").strip()
        categoria = request.form.get(
            "categoria",
            "Matéria-prima",
        ).strip()

        if not nome or not unidade:
            flash("Preencha o nome e a unidade do insumo.")
            return redirect(url_for("insumos"))

        novo = Insumo(
            nome=nome,
            unidade=unidade,
            categoria=categoria or "Matéria-prima",
        )

        db.session.add(novo)
        db.session.commit()

        flash("Insumo cadastrado com sucesso!")
        return redirect(url_for("insumos"))

    lista = Insumo.query.order_by(Insumo.nome).all()

    return render_template(
        "insumos.html",
        insumos=lista,
    )


@app.route("/entrada_estoque/<int:insumo_id>", methods=["POST"])
def entrada_estoque(insumo_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    insumo = Insumo.query.get_or_404(insumo_id)

    quantidade = converter_float(
        request.form.get("quantidade")
    )

    valor_total = converter_float(
        request.form.get("valor_total")
    )

    if quantidade <= 0:
        flash("A quantidade da entrada deve ser maior que zero.")
        return redirect(url_for("insumos"))

    if valor_total < 0:
        flash("O valor total não pode ser negativo.")
        return redirect(url_for("insumos"))

    try:
        entrada = MovimentacaoEstoque(
            insumo_id=insumo_id,
            tipo="Entrada",
            quantidade=quantidade,
            valor_total=valor_total,
            observacao="Compra registrada",
        )

        saida_financeira = Financeiro(
            tipo="Saída",
            categoria="Compra de insumos",
            descricao=f"Compra de {insumo.nome}",
            valor=valor_total,
        )

        db.session.add(entrada)
        db.session.add(saida_financeira)
        db.session.commit()

        flash("Entrada de estoque registrada com sucesso!")

    except Exception:
        db.session.rollback()
        flash("Não foi possível registrar a entrada de estoque.")

    return redirect(url_for("insumos"))


@app.route("/insumos/editar/<int:id>", methods=["GET", "POST"])
def editar_insumo(id):
    if not usuario_logado():
        return redirect(url_for("login"))

    insumo = Insumo.query.get_or_404(id)

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        unidade = request.form.get("unidade", "").strip()
        categoria = request.form.get(
            "categoria",
            "Matéria-prima",
        ).strip()

        if not nome or not unidade:
            flash("Preencha o nome e a unidade do insumo.")
            return redirect(
                url_for("editar_insumo", id=insumo.id)
            )

        insumo.nome = nome
        insumo.unidade = unidade
        insumo.categoria = categoria or "Matéria-prima"

        db.session.commit()

        flash("Insumo atualizado com sucesso!")
        return redirect(url_for("insumos"))

    return render_template(
        "editar_insumo.html",
        insumo=insumo,
    )


@app.route("/excluir_insumo/<int:id>", methods=["POST", "GET"])
def excluir_insumo(id):
    if not usuario_logado():
        return redirect(url_for("login"))

    insumo = Insumo.query.get_or_404(id)

    if getattr(insumo, "movimentacoes", None):
        flash(
            "Este insumo não pode ser excluído porque possui movimentações."
        )
        return redirect(url_for("insumos"))

    itens_ficha = FichaTecnica.query.filter_by(
        insumo_id=insumo.id
    ).count()

    if itens_ficha:
        flash(
            "Este insumo não pode ser excluído porque está em uma ficha técnica."
        )
        return redirect(url_for("insumos"))

    db.session.delete(insumo)
    db.session.commit()

    flash("Insumo excluído com sucesso!")
    return redirect(url_for("insumos"))


@app.route("/produtos", methods=["GET", "POST"])
def produtos():
    if not usuario_logado():
        return redirect(url_for("login"))

    if request.method == "POST":
        tipo_produto = request.form.get(
            "tipo_produto",
            "Produzido",
        ).strip()

        finalidade = request.form.get(
            "finalidade",
            "Venda",
        ).strip()

        nome = request.form.get(
            "nome",
            "",
        ).strip()

        categoria = request.form.get(
            "categoria",
            "",
        ).strip()

        preco_venda = converter_float(
            request.form.get("preco_venda")
        )

        custo_compra = converter_float(
            request.form.get("custo_compra")
        )

        estoque_produto = converter_float(
            request.form.get("estoque_produto")
        )

        rendimento_quantidade = converter_float(
            request.form.get("rendimento_quantidade"),
            1.0,
        )

        rendimento_unidade = request.form.get(
            "rendimento_unidade",
            "un",
        ).strip()

        if not nome or not categoria:
            flash(
                "Preencha o nome e a categoria do produto.",
                "erro",
            )
            return redirect(url_for("produtos"))

        unidades_validas = {
            "un",
            "kg",
            "g",
            "L",
            "ml",
        }

        if rendimento_unidade not in unidades_validas:
            rendimento_unidade = "un"

        if tipo_produto == "Revenda":
            rendimento_quantidade = 1.0
            rendimento_unidade = "un"

        else:
            custo_compra = 0
            estoque_produto = 0

            if rendimento_quantidade <= 0:
                flash(
                    "O rendimento do produto produzido deve ser maior que zero.",
                    "erro",
                )
                return redirect(url_for("produtos"))

        if finalidade == "Preparo Interno":
            preco_venda = 0

        novo = Produto(
            nome=nome,
            categoria=categoria,
            preco_venda=preco_venda,
            tipo_produto=tipo_produto,
            finalidade=finalidade,
            custo_compra=custo_compra,
            estoque_produto=estoque_produto,
            rendimento_quantidade=rendimento_quantidade,
            rendimento_unidade=rendimento_unidade,
            ativo=True,
        )

        try:
            db.session.add(novo)
            db.session.commit()

            flash(
                "Produto cadastrado com sucesso!",
                "sucesso",
            )

        except Exception:
            db.session.rollback()

            flash(
                "Não foi possível cadastrar o produto.",
                "erro",
            )

        return redirect(url_for("produtos"))

    lista = Produto.query.order_by(
        Produto.nome
    ).all()

    return render_template(
        "produtos.html",
        produtos=lista,
    )


@app.route(
    "/editar_produto/<int:id>",
    methods=["POST"],
)
def editar_produto(id):
    if not usuario_logado():
        return redirect(url_for("login"))

    produto = Produto.query.get_or_404(id)

    nome = request.form.get(
        "nome",
        produto.nome,
    ).strip()

    categoria = request.form.get(
        "categoria",
        produto.categoria or "",
    ).strip()

    tipo_produto = request.form.get(
        "tipo_produto",
        produto.tipo_produto or "Produzido",
    ).strip()

    finalidade = request.form.get(
        "finalidade",
        produto.finalidade or "Venda",
    ).strip()

    preco_venda = converter_float(
        request.form.get("preco_venda")
    )

    custo_compra = converter_float(
        request.form.get("custo_compra")
    )

    estoque_produto = converter_float(
        request.form.get("estoque_produto")
    )

    rendimento_quantidade = converter_float(
        request.form.get("rendimento_quantidade"),
        produto.rendimento_quantidade or 1.0,
    )

    rendimento_unidade = request.form.get(
        "rendimento_unidade",
        produto.rendimento_unidade or "un",
    ).strip()

    if not nome or not categoria:
        flash(
            "Preencha o nome e a categoria do produto.",
            "erro",
        )
        return redirect(url_for("produtos"))

    unidades_validas = {
        "un",
        "kg",
        "g",
        "L",
        "ml",
    }

    if rendimento_unidade not in unidades_validas:
        rendimento_unidade = "un"

    if tipo_produto == "Revenda":
        rendimento_quantidade = 1.0
        rendimento_unidade = "un"

    else:
        custo_compra = 0
        estoque_produto = 0

        if rendimento_quantidade <= 0:
            flash(
                "O rendimento do produto produzido deve ser maior que zero.",
                "erro",
            )
            return redirect(url_for("produtos"))

    if finalidade == "Preparo Interno":
        preco_venda = 0

    produto.nome = nome
    produto.categoria = categoria
    produto.preco_venda = preco_venda
    produto.tipo_produto = tipo_produto
    produto.finalidade = finalidade
    produto.custo_compra = custo_compra
    produto.estoque_produto = estoque_produto
    produto.rendimento_quantidade = rendimento_quantidade
    produto.rendimento_unidade = rendimento_unidade

    try:
        db.session.commit()

        flash(
            "Produto atualizado com sucesso!",
            "sucesso",
        )

    except Exception:
        db.session.rollback()

        flash(
            "Não foi possível atualizar o produto.",
            "erro",
        )

    return redirect(url_for("produtos"))


@app.route(
    "/excluir_produto/<int:id>",
    methods=["POST", "GET"],
)
def excluir_produto(id):
    if not usuario_logado():
        return redirect(url_for("login"))

    produto = Produto.query.get_or_404(id)

    if getattr(
        produto,
        "fichas_como_base",
        None,
    ):
        flash(
            "Este produto não pode ser excluído porque está sendo usado "
            "como preparo interno.",
            "erro",
        )
        return redirect(url_for("produtos"))

    if produto.ficha_itens:
        flash(
            "Exclua primeiro os itens da ficha técnica deste produto.",
            "erro",
        )
        return redirect(url_for("produtos"))

    if getattr(
        produto,
        "vendas",
        None,
    ):
        flash(
            "Este produto não pode ser excluído porque possui vendas registradas.",
            "erro",
        )
        return redirect(url_for("produtos"))

    try:
        db.session.delete(produto)
        db.session.commit()

        flash(
            "Produto excluído com sucesso!",
            "sucesso",
        )

    except Exception:
        db.session.rollback()

        flash(
            "Não foi possível excluir o produto.",
            "erro",
        )

    return redirect(url_for("produtos"))


@app.route(
    "/alterar_status_produto/<int:id>",
    methods=["POST", "GET"],
)
def alterar_status_produto(id):
    if not usuario_logado():
        return redirect(url_for("login"))

    produto = Produto.query.get_or_404(id)
    produto.ativo = not produto.ativo

    try:
        db.session.commit()

        flash(
            "Status do produto atualizado!",
            "sucesso",
        )

    except Exception:
        db.session.rollback()

        flash(
            "Não foi possível alterar o status do produto.",
            "erro",
        )

    return redirect(url_for("produtos"))


@app.route("/ficha_tecnica", methods=["GET", "POST"])
def ficha_tecnica():
    if not usuario_logado():
        return redirect(url_for("login"))

    produto_selecionado_id = request.args.get(
        "produto_id",
        type=int
    )

    if request.method == "POST":
        produto_id = request.form.get(
            "produto_id",
            type=int
        )

        tipo_item = request.form.get(
            "tipo_item",
            ""
        ).strip()

        quantidade = converter_float(
            request.form.get("quantidade")
        )

        unidade_utilizada = request.form.get(
            "unidade_utilizada",
            ""
        ).strip()

        # =========================
        # VALIDAÇÃO DO PRODUTO
        # =========================

        if not produto_id:
            flash(
                "Selecione o produto da ficha técnica.",
                "erro"
            )
            return redirect(
                url_for("ficha_tecnica")
            )

        produto = Produto.query.get_or_404(
            produto_id
        )

        # =========================
        # VALIDAÇÃO DA QUANTIDADE
        # =========================

        if quantidade <= 0:
            flash(
                "A quantidade deve ser maior que zero.",
                "erro"
            )
            return redirect(
                url_for(
                    "ficha_tecnica",
                    produto_id=produto_id
                )
            )

        # =========================
        # VALIDAÇÃO DA UNIDADE
        # =========================

        unidades_permitidas = {
            "g",
            "kg",
            "ml",
            "L",
            "un"
        }

        if unidade_utilizada not in unidades_permitidas:
            flash(
                "Selecione uma unidade de medida válida.",
                "erro"
            )
            return redirect(
                url_for(
                    "ficha_tecnica",
                    produto_id=produto_id
                )
            )

        # =========================
        # NOVO ITEM DA FICHA
        # =========================

        item = FichaTecnica(
            produto_id=produto_id,
            quantidade=quantidade,
            unidade_utilizada=unidade_utilizada
        )

        # =========================
        # COMPONENTE DO TIPO INSUMO
        # =========================

        if tipo_item == "insumo":
            insumo_id = request.form.get(
                "insumo_id",
                type=int
            )

            if not insumo_id:
                flash(
                    "Selecione um insumo.",
                    "erro"
                )
                return redirect(
                    url_for(
                        "ficha_tecnica",
                        produto_id=produto_id
                    )
                )

            insumo = Insumo.query.get_or_404(
                insumo_id
            )

            # Impede o mesmo insumo de ser
            # adicionado duas vezes à ficha
            item_existente = FichaTecnica.query.filter_by(
                produto_id=produto_id,
                insumo_id=insumo_id
            ).first()

            if item_existente:
                flash(
                    f"O insumo '{insumo.nome}' já está "
                    f"cadastrado na ficha de "
                    f"'{produto.nome}'.",
                    "erro"
                )
                return redirect(
                    url_for(
                        "ficha_tecnica",
                        produto_id=produto_id
                    )
                )

            item.insumo_id = insumo_id
            item.produto_base_id = None

        # =============================
        # COMPONENTE: PREPARO INTERNO
        # =============================

        elif tipo_item == "produto":
            produto_base_id = request.form.get(
                "produto_base_id",
                type=int
            )

            if not produto_base_id:
                flash(
                    "Selecione um preparo interno.",
                    "erro"
                )
                return redirect(
                    url_for(
                        "ficha_tecnica",
                        produto_id=produto_id
                    )
                )

            produto_base = Produto.query.get_or_404(
                produto_base_id
            )

            # Impede o produto de usar ele mesmo
            if produto_base.id == produto.id:
                flash(
                    "Um produto não pode utilizar a si "
                    "mesmo como componente.",
                    "erro"
                )
                return redirect(
                    url_for(
                        "ficha_tecnica",
                        produto_id=produto_id
                    )
                )

            # Somente preparos internos produzidos
            # podem ser usados como produto-base
            if (
                produto_base.tipo_produto != "Produzido"
                or produto_base.finalidade
                != "Preparo Interno"
            ):
                flash(
                    "Somente preparos internos produzidos "
                    "pela empresa podem ser utilizados "
                    "como base.",
                    "erro"
                )
                return redirect(
                    url_for(
                        "ficha_tecnica",
                        produto_id=produto_id
                    )
                )

            # Impede o mesmo preparo interno de ser
            # adicionado duas vezes
            item_existente = FichaTecnica.query.filter_by(
                produto_id=produto_id,
                produto_base_id=produto_base_id
            ).first()

            if item_existente:
                flash(
                    f"O preparo interno "
                    f"'{produto_base.nome}' já está "
                    f"cadastrado na ficha de "
                    f"'{produto.nome}'.",
                    "erro"
                )
                return redirect(
                    url_for(
                        "ficha_tecnica",
                        produto_id=produto_id
                    )
                )

            # Impede referências circulares
            if ficha_cria_ciclo(
                produto_id,
                produto_base_id
            ):
                flash(
                    "Essa inclusão criaria uma "
                    "referência circular entre as "
                    "fichas técnicas.",
                    "erro"
                )
                return redirect(
                    url_for(
                        "ficha_tecnica",
                        produto_id=produto_id
                    )
                )

            item.insumo_id = None
            item.produto_base_id = produto_base_id

        else:
            flash(
                "Selecione se o componente é um "
                "insumo ou um preparo interno.",
                "erro"
            )
            return redirect(
                url_for(
                    "ficha_tecnica",
                    produto_id=produto_id
                )
            )

        # =========================
        # SALVAMENTO
        # =========================

        try:
            db.session.add(item)
            db.session.commit()

            flash(
                "Componente adicionado à ficha "
                "técnica com sucesso!",
                "sucesso"
            )

        except Exception:
            db.session.rollback()

            flash(
                "Não foi possível adicionar o "
                "componente à ficha técnica.",
                "erro"
            )

        return redirect(
            url_for(
                "ficha_tecnica",
                produto_id=produto_id
            )
        )

    # =========================
    # LISTA DE PRODUTOS
    # =========================

    produtos_lista = Produto.query.filter_by(
        ativo=True
    ).order_by(
        Produto.nome
    ).all()

    # =========================
    # PREPAROS INTERNOS
    # =========================

    produtos_base = Produto.query.filter_by(
        tipo_produto="Produzido",
        finalidade="Preparo Interno",
        ativo=True
    ).order_by(
        Produto.nome
    ).all()

    # =========================
    # LISTA DE INSUMOS
    # =========================

    insumos_lista = Insumo.query.order_by(
        Insumo.nome
    ).all()

    produto_selecionado = None
    itens = []

    # Mostra somente a ficha do
    # produto selecionado
    if produto_selecionado_id:
        produto_selecionado = (
            Produto.query.get_or_404(
                produto_selecionado_id
            )
        )

        itens = FichaTecnica.query.filter_by(
            produto_id=produto_selecionado_id
        ).order_by(
            FichaTecnica.id
        ).all()

    return render_template(
        "ficha_tecnica.html",
        produtos=produtos_lista,
        produtos_base=produtos_base,
        insumos=insumos_lista,
        produto_selecionado=produto_selecionado,
        produto_selecionado_id=produto_selecionado_id,
        itens=itens
    )


@app.route(
    "/excluir_item_ficha/<int:id>",
    methods=["POST"]
)
def excluir_item_ficha(id):
    if not usuario_logado():
        return redirect(url_for("login"))

    item = FichaTecnica.query.get_or_404(id)

    produto_id = item.produto_id

    try:
        db.session.delete(item)
        db.session.commit()

        flash(
            "Componente removido da ficha técnica.",
            "sucesso"
        )

    except Exception:
        db.session.rollback()

        flash(
            "Não foi possível remover o componente "
            "da ficha técnica.",
            "erro"
        )

    return redirect(
        url_for(
            "ficha_tecnica",
            produto_id=produto_id
        )
    )


@app.route("/vendas", methods=["GET", "POST"])
def vendas():
    if not usuario_logado():
        return redirect(url_for("login"))

    hoje = datetime.now().date()

    # =====================================================
    # REGISTRAR VENDA
    # =====================================================

    if request.method == "POST":
        produto_id = request.form.get(
            "produto_id"
        )

        quantidade_vendida = int(
            converter_float(
                request.form.get("quantidade")
            )
        )

        data_texto = request.form.get(
            "data_venda",
            ""
        ).strip()

        # -------------------------------------------------
        # VALIDAÇÕES INICIAIS
        # -------------------------------------------------

        if not produto_id:
            flash(
                "Selecione um produto.",
                "erro"
            )
            return redirect(url_for("vendas"))

        if quantidade_vendida <= 0:
            flash(
                "A quantidade vendida deve ser maior que zero.",
                "erro"
            )
            return redirect(url_for("vendas"))

        if not data_texto:
            flash(
                "Informe a data da venda.",
                "erro"
            )
            return redirect(url_for("vendas"))

        try:
            data_venda = datetime.strptime(
                data_texto,
                "%Y-%m-%d"
            )

        except ValueError:
            flash(
                "A data informada é inválida.",
                "erro"
            )
            return redirect(url_for("vendas"))

        if data_venda.date() > hoje:
            flash(
                "Não é possível registrar uma venda com data futura.",
                "erro"
            )
            return redirect(url_for("vendas"))

        # Venda anterior ao dia de hoje:
        # registra os valores, mas não altera o estoque.
        venda_retroativa = (
            data_venda.date() < hoje
        )

        movimentar_estoque = (
            not venda_retroativa
        )

        produto = Produto.query.get_or_404(
            int(produto_id)
        )

        if not produto.ativo:
            flash(
                "Este produto está inativo.",
                "erro"
            )
            return redirect(url_for("vendas"))

        if produto.finalidade == "Preparo Interno":
            flash(
                "Preparos internos não podem ser vendidos diretamente.",
                "erro"
            )
            return redirect(url_for("vendas"))

        if (
            produto.tipo_produto == "Produzido"
            and not produto.ficha_itens
        ):
            flash(
                "Este produto ainda não possui ficha técnica cadastrada.",
                "erro"
            )
            return redirect(url_for("vendas"))

        try:
            consumos = []

            # =================================================
            # VENDA ATUAL DE PRODUTO PRODUZIDO
            # =================================================
            # Só calcula e verifica o estoque quando a venda
            # for registrada com a data de hoje.

            if (
                movimentar_estoque
                and produto.tipo_produto == "Produzido"
            ):
                consumos = calcular_consumo_insumos(
                    produto,
                    multiplicador=quantidade_vendida,
                )

                consumo_agrupado = {}

                for insumo, quantidade in consumos:
                    if insumo.id not in consumo_agrupado:
                        consumo_agrupado[insumo.id] = {
                            "insumo": insumo,
                            "quantidade": 0.0,
                        }

                    consumo_agrupado[
                        insumo.id
                    ]["quantidade"] += float(
                        quantidade or 0
                    )

                faltas = []

                for dados in consumo_agrupado.values():
                    insumo = dados["insumo"]

                    quantidade_necessaria = float(
                        dados["quantidade"] or 0
                    )

                    estoque_disponivel = float(
                        insumo.estoque_atual() or 0
                    )

                    if (
                        estoque_disponivel
                        < quantidade_necessaria
                    ):
                        faltas.append(
                            f"{insumo.nome}: necessário "
                            f"{quantidade_necessaria:.3f}, "
                            f"disponível "
                            f"{estoque_disponivel:.3f}"
                        )

                if faltas:
                    flash(
                        "Estoque insuficiente: "
                        + "; ".join(faltas),
                        "erro"
                    )
                    return redirect(
                        url_for("vendas")
                    )

            # =================================================
            # VENDA ATUAL DE PRODUTO DE REVENDA
            # =================================================

            if (
                movimentar_estoque
                and produto.tipo_produto == "Revenda"
            ):
                estoque_revenda = float(
                    produto.estoque_produto or 0
                )

                if estoque_revenda < quantidade_vendida:
                    flash(
                        "Estoque insuficiente para este "
                        "produto de revenda.",
                        "erro"
                    )
                    return redirect(
                        url_for("vendas")
                    )

            # =================================================
            # CÁLCULOS DA VENDA
            # =================================================

            preco_unitario = float(
                produto.preco_venda or 0
            )

            custo_unitario = float(
                produto.custo_materia_prima() or 0
            )

            receita_total = (
                preco_unitario
                * quantidade_vendida
            )

            cmv_total = (
                custo_unitario
                * quantidade_vendida
            )

            margem_total = (
                receita_total
                - cmv_total
            )

            # =================================================
            # CRIAÇÃO DA VENDA
            # =================================================

            venda = Venda(
                data=data_venda,
                produto_id=produto.id,
                quantidade=quantidade_vendida,
                receita_total=receita_total,
                cmv_total=cmv_total,
                margem_total=margem_total,
                movimentou_estoque=movimentar_estoque,
            )

            db.session.add(venda)
            db.session.flush()

            # =================================================
            # BAIXA DE INSUMOS — APENAS VENDA DO DIA
            # =================================================

            if (
                movimentar_estoque
                and produto.tipo_produto == "Produzido"
            ):
                for insumo, quantidade_saida in consumos:
                    quantidade_saida = float(
                        quantidade_saida or 0
                    )

                    custo_unitario_insumo = float(
                        insumo.custo_medio_unitario()
                        or 0
                    )

                    custo_saida = (
                        quantidade_saida
                        * custo_unitario_insumo
                    )

                    saida = MovimentacaoEstoque(
                        insumo_id=insumo.id,
                        tipo="Saída",
                        quantidade=quantidade_saida,
                        valor_total=custo_saida,
                        observacao=(
                            f"Venda de "
                            f"{quantidade_vendida} un. "
                            f"- {produto.nome}"
                        ),
                        venda_id=venda.id,
                    )

                    db.session.add(saida)

            # =================================================
            # BAIXA DA REVENDA — APENAS VENDA DO DIA
            # =================================================

            elif (
                movimentar_estoque
                and produto.tipo_produto == "Revenda"
            ):
                produto.estoque_produto = (
                    float(
                        produto.estoque_produto or 0
                    )
                    - quantidade_vendida
                )

            db.session.commit()

            if venda_retroativa:
                flash(
                    "Venda retroativa registrada com sucesso. "
                    "O estoque atual não foi alterado.",
                    "sucesso"
                )

            else:
                flash(
                    "Venda registrada e estoque atualizado!",
                    "sucesso"
                )

        except ValueError as erro:
            db.session.rollback()

            flash(
                str(erro),
                "erro"
            )

        except Exception as erro:
            db.session.rollback()

            print(
                f"Erro ao registrar venda: {erro}"
            )

            flash(
                "Não foi possível registrar a venda.",
                "erro"
            )

        return redirect(url_for("vendas"))

    # =====================================================
    # ABERTURA DA PÁGINA DE VENDAS
    # =====================================================

    produtos_lista = Produto.query.filter_by(
        ativo=True,
        finalidade="Venda",
    ).order_by(
        Produto.nome
    ).all()

    vendas_lista = Venda.query.order_by(
        Venda.data.desc(),
        Venda.id.desc(),
    ).all()

    # =====================================================
    # INDICADORES MOSTRADOS NO TOPO DA PÁGINA
    # =====================================================

    receita_total = sum(
        float(venda.receita_total or 0)
        for venda in vendas_lista
    )

    cmv_total = sum(
        float(venda.cmv_total or 0)
        for venda in vendas_lista
    )

    margem_total = sum(
        float(venda.margem_total or 0)
        for venda in vendas_lista
    )

    quantidade_total = sum(
        int(venda.quantidade or 0)
        for venda in vendas_lista
    )

    vendas_retroativas = sum(
        1
        for venda in vendas_lista
        if not venda.movimentou_estoque
    )

    return render_template(
        "vendas.html",
        produtos=produtos_lista,
        vendas=vendas_lista,
        receita_total=receita_total,
        cmv_total=cmv_total,
        margem_total=margem_total,
        quantidade_total=quantidade_total,
        vendas_retroativas=vendas_retroativas,
        data_hoje=hoje.strftime("%Y-%m-%d"),
    )


@app.route(
    "/excluir_venda/<int:id>",
    methods=["POST"],
)
def excluir_venda(id):
    if not usuario_logado():
        return redirect(url_for("login"))

    venda = Venda.query.get_or_404(id)
    produto = venda.produto

    # Guardamos essa informação antes de excluir.
    movimentou_estoque = bool(
        venda.movimentou_estoque
    )

    try:
        # Venda do dia:
        # exclui as movimentações e restaura o estoque.
        if movimentou_estoque:
            movimentacoes = (
                MovimentacaoEstoque.query.filter_by(
                    venda_id=venda.id
                ).all()
            )

            for movimentacao in movimentacoes:
                db.session.delete(
                    movimentacao
                )

            # Produto de revenda tem o saldo armazenado
            # diretamente na tabela Produto.
            if (
                produto
                and produto.tipo_produto == "Revenda"
            ):
                produto.estoque_produto = (
                    float(
                        produto.estoque_produto or 0
                    )
                    + int(venda.quantidade or 0)
                )

        # Venda retroativa:
        # apenas exclui o registro, sem alterar estoque.

        db.session.delete(venda)
        db.session.commit()

        if movimentou_estoque:
            flash(
                "Venda excluída e estoque restaurado!",
                "sucesso"
            )

        else:
            flash(
                "Lançamento retroativo excluído. "
                "O estoque não foi alterado.",
                "sucesso"
            )

    except Exception as erro:
        db.session.rollback()

        print(
            f"Erro ao excluir venda: {erro}"
        )

        flash(
            "Não foi possível excluir a venda.",
            "erro"
        )

    return redirect(url_for("vendas"))

@app.route("/financeiro", methods=["GET", "POST"])
def financeiro():
    if not usuario_logado():
        return redirect(url_for("login"))

    if request.method == "POST":
        valor = converter_float(
            request.form.get("valor")
        )

        if valor <= 0:
            flash("O valor deve ser maior que zero.")
            return redirect(url_for("financeiro"))

        novo = Financeiro(
            tipo=request.form.get("tipo", "Saída"),
            categoria=request.form.get(
                "categoria",
                "",
            ).strip(),
            descricao=request.form.get(
                "descricao",
                "",
            ).strip(),
            valor=valor,
        )

        db.session.add(novo)
        db.session.commit()

        flash("Lançamento financeiro registrado!")
        return redirect(url_for("financeiro"))

    registros = Financeiro.query.order_by(
        Financeiro.data.desc()
    ).all()

    total_entradas = sum(
        registro.valor
        for registro in registros
        if registro.tipo == "Entrada"
    )

    total_saidas = sum(
        registro.valor
        for registro in registros
        if registro.tipo == "Saída"
    )

    saldo = total_entradas - total_saidas

    return render_template(
        "financeiro.html",
        registros=registros,
        total_entradas=total_entradas,
        total_saidas=total_saidas,
        saldo=saldo,
    )


@app.route("/excluir_financeiro/<int:id>", methods=["POST", "GET"])
def excluir_financeiro(id):
    if not usuario_logado():
        return redirect(url_for("login"))

    registro = Financeiro.query.get_or_404(id)

    db.session.delete(registro)
    db.session.commit()

    flash("Lançamento financeiro excluído!")
    return redirect(url_for("financeiro"))


@app.route("/relatorios")
def relatorios():
    if not usuario_logado():
        return redirect(url_for("login"))

    insumos_lista = Insumo.query.order_by(
        Insumo.nome
    ).all()

    produtos_lista = Produto.query.order_by(
        Produto.nome
    ).all()

    vendas_lista = Venda.query.order_by(
        Venda.data.desc()
    ).all()

    financeiros = Financeiro.query.order_by(
        Financeiro.data.desc()
    ).all()

    receita_total = sum(
        venda.receita_total or 0
        for venda in vendas_lista
    )

    cmv_total = sum(
        venda.cmv_total or 0
        for venda in vendas_lista
    )

    margem_total = sum(
        venda.margem_total or 0
        for venda in vendas_lista
    )

    despesas_operacionais = sum(
        financeiro.valor or 0
        for financeiro in financeiros
        if financeiro.tipo == "Saída"
    )

    lucro_operacional = (
        margem_total
        - despesas_operacionais
    )

    margem_percentual = 0

    if receita_total > 0:
        margem_percentual = (
            margem_total / receita_total
        ) * 100

    valor_estoque = sum(
        insumo.estoque_atual()
        * insumo.custo_medio_unitario()
        for insumo in insumos_lista
    )

    valor_estoque_produtos = sum(
        (produto.estoque_produto or 0)
        * (
            produto.custo_compra
            if produto.tipo_produto == "Revenda"
            else produto.custo_materia_prima()
        )
        for produto in produtos_lista
    )

    valor_estoque += valor_estoque_produtos

    total_vendido = sum(
        venda.quantidade or 0
        for venda in vendas_lista
    )

    itens_abaixo_minimo = sum(
        1
        for insumo in insumos_lista
        if insumo.estoque_atual()
        <= insumo.estoque_minimo()
    )

    itens_ponto_pedido = sum(
        1
        for insumo in insumos_lista
        if insumo.estoque_minimo()
        < insumo.estoque_atual()
        <= insumo.ponto_pedido()
    )

    coberturas = []

    for insumo in insumos_lista:
        cobertura = insumo.cobertura_estoque()

        if cobertura > 0:
            coberturas.append(cobertura)

    cobertura_media = (
        sum(coberturas) / len(coberturas)
        if coberturas
        else 0
    )

    giros = []

    for insumo in insumos_lista:
        giro = insumo.giro_estoque()

        if giro > 0:
            giros.append(giro)

    giro_medio = (
        sum(giros) / len(giros)
        if giros
        else 0
    )

    lotes = []

    for insumo in insumos_lista:
        lote = insumo.lote_economico()

        if lote > 0:
            lotes.append(lote)

    lote_economico_medio = (
        sum(lotes) / len(lotes)
        if lotes
        else 0
    )

    ranking_produtos = {}

    for venda in vendas_lista:
        if venda.produto is None:
            continue

        nome_produto = venda.produto.nome

        if nome_produto not in ranking_produtos:
            ranking_produtos[nome_produto] = {
                "quantidade": 0,
                "receita": 0,
                "cmv": 0,
                "margem": 0,
            }

        ranking_produtos[nome_produto]["quantidade"] += (
            venda.quantidade or 0
        )

        ranking_produtos[nome_produto]["receita"] += (
            venda.receita_total or 0
        )

        ranking_produtos[nome_produto]["cmv"] += (
            venda.cmv_total or 0
        )

        ranking_produtos[nome_produto]["margem"] += (
            venda.margem_total or 0
        )

    ranking_produtos = sorted(
        ranking_produtos.items(),
        key=lambda item: item[1]["quantidade"],
        reverse=True,
    )

    return render_template(
        "relatorios.html",
        insumos=insumos_lista,
        produtos=produtos_lista,
        vendas=vendas_lista,
        financeiros=financeiros,
        receita_total=receita_total,
        cmv_total=cmv_total,
        margem_total=margem_total,
        margem_percentual=margem_percentual,
        despesas_operacionais=despesas_operacionais,
        lucro_operacional=lucro_operacional,
        valor_estoque=valor_estoque,
        total_vendido=total_vendido,
        ranking_produtos=ranking_produtos,
        itens_abaixo_minimo=itens_abaixo_minimo,
        itens_ponto_pedido=itens_ponto_pedido,
        cobertura_media=cobertura_media,
        giro_medio=giro_medio,
        lote_economico_medio=lote_economico_medio,
    )


@app.route("/exportar_caixa")
def exportar_caixa():
    if not usuario_logado():
        return redirect(url_for("login"))

    vendas_lista = Venda.query.order_by(
        Venda.data.asc()
    ).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Caixa"

    ws["A1"] = "ERP RESTAURANTE"
    ws["A2"] = "FECHAMENTO DE CAIXA"
    ws["A3"] = (
        "Data de emissão: "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )

    ws.append([])

    ws.append(
        [
            "Data",
            "Produto",
            "Quantidade",
            "Receita",
            "CMV",
            "Margem de Contribuição",
        ]
    )

    receita_total = 0
    cmv_total = 0
    margem_total = 0
    quantidade_total = 0

    for venda in vendas_lista:
        nome_produto = (
            venda.produto.nome
            if venda.produto
            else "Produto removido"
        )

        ws.append(
            [
                venda.data.strftime("%d/%m/%Y %H:%M"),
                nome_produto,
                venda.quantidade,
                venda.receita_total,
                venda.cmv_total,
                venda.margem_total,
            ]
        )

        receita_total += venda.receita_total or 0
        cmv_total += venda.cmv_total or 0
        margem_total += venda.margem_total or 0
        quantidade_total += venda.quantidade or 0

    ws.append([])
    ws.append(["RESUMO DO CAIXA"])
    ws.append(["Quantidade vendida", quantidade_total])
    ws.append(["Receita total", receita_total])
    ws.append(["CMV total", cmv_total])
    ws.append(["Margem de contribuição", margem_total])

    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 15
    ws.column_dimensions["D"].width = 15
    ws.column_dimensions["E"].width = 15
    ws.column_dimensions["F"].width = 25

    for linha in ws.iter_rows(
        min_row=6,
        min_col=4,
        max_col=6,
    ):
        for celula in linha:
            celula.number_format = 'R$ #,##0.00'

    arquivo = io.BytesIO()
    wb.save(arquivo)
    arquivo.seek(0)

    nome_arquivo = (
        "Fechamento_Caixa_"
        f"{datetime.now().strftime('%d-%m-%Y')}.xlsx"
    )

    return send_file(
        arquivo,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )


@app.route("/configuracoes")
def configuracoes():
    if not usuario_logado():
        return redirect(url_for("login"))

    total_insumos = Insumo.query.count()
    total_produtos = Produto.query.count()
    total_vendas = Venda.query.count()
    total_lancamentos = Financeiro.query.count()

    return render_template(
        "configuracoes.html",
        nome=session.get("usuario_nome"),
        total_insumos=total_insumos,
        total_produtos=total_produtos,
        total_vendas=total_vendas,
        total_lancamentos=total_lancamentos,
    )


@app.route("/fazer_backup")
def fazer_backup():
    if not usuario_logado():
        return redirect(url_for("login"))

    uri_banco = app.config["SQLALCHEMY_DATABASE_URI"]

    if not uri_banco.startswith("sqlite:///"):
        flash(
            "O backup local automático está disponível apenas para SQLite."
        )
        return redirect(url_for("configuracoes"))

    caminho_relativo = uri_banco.replace(
        "sqlite:///",
        "",
        1,
    )

    if os.path.isabs(caminho_relativo):
        origem = caminho_relativo
    else:
        origem = os.path.join(
            app.instance_path,
            caminho_relativo,
        )

    pasta_backup = os.path.join(
        app.root_path,
        "backups",
    )

    os.makedirs(
        pasta_backup,
        exist_ok=True,
    )

    data_hora = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    destino = os.path.join(
        pasta_backup,
        f"backup_{data_hora}.db",
    )

    if os.path.exists(origem):
        shutil.copy2(origem, destino)
        flash("Backup realizado com sucesso!")
    else:
        flash(
            f"Banco de dados não encontrado em: {origem}"
        )

    return redirect(url_for("configuracoes"))


@app.route("/alterar_senha", methods=["POST"])
def alterar_senha():
    if not usuario_logado():
        return redirect(url_for("login"))

    usuario = db.session.get(
        Usuario,
        session["usuario_id"],
    )

    if usuario is None:
        session.clear()
        flash("Sua sessão expirou. Entre novamente.")
        return redirect(url_for("login"))

    senha_atual = request.form.get(
        "senha_atual",
        "",
    )

    nova_senha = request.form.get(
        "nova_senha",
        "",
    )

    confirmar = request.form.get(
        "confirmar_senha",
        "",
    )

    if not usuario.verificar_senha(senha_atual):
        flash("Senha atual incorreta.")
        return redirect(url_for("configuracoes"))

    if len(nova_senha) < 6:
        flash("A nova senha deve ter pelo menos 6 caracteres.")
        return redirect(url_for("configuracoes"))

    if nova_senha != confirmar:
        flash("As novas senhas não coincidem.")
        return redirect(url_for("configuracoes"))

    usuario.set_senha(nova_senha)
    db.session.commit()

    flash("Senha alterada com sucesso!")
    return redirect(url_for("configuracoes"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)