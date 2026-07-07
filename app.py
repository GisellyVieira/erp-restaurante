from flask import Flask, render_template, request, redirect, url_for, session, flash
from models import (
    db,
    Usuario,
    Insumo,
    MovimentacaoEstoque,
    Produto,
    FichaTecnica,
    Venda,
    Financeiro
)

from flask import send_file
from openpyxl import Workbook
import io
from datetime import datetime
import os
import shutil


app = Flask(__name__)

app.config["SECRET_KEY"] = "chave-secreta-do-sistema"
import os

database_url = os.environ.get("DATABASE_URL")

if database_url:
    database_url = database_url.replace("postgres://", "postgresql://")

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


def criar_banco():
    with app.app_context():
        db.create_all()

        admin = Usuario.query.filter_by(usuario="admin").first()

        if not admin:
            admin = Usuario(nome="Gerente", usuario="admin")
            admin.set_senha("123456")
            db.session.add(admin)
            db.session.commit()


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario")
        senha = request.form.get("senha")

        user = Usuario.query.filter_by(usuario=usuario).first()

        if user and user.verificar_senha(senha):
            session["usuario_id"] = user.id
            session["usuario_nome"] = user.nome
            return redirect(url_for("dashboard"))

        flash("Usuário ou senha incorretos!")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    insumos = Insumo.query.all()
    produtos = Produto.query.all()
    vendas = Venda.query.all()
    financeiros = Financeiro.query.all()

    receita_vendas = sum(v.receita_total for v in vendas)
    cmv_total = sum(v.cmv_total for v in vendas)
    margem_total = sum(v.margem_total for v in vendas)

    entradas_financeiras = sum(f.valor for f in financeiros if f.tipo == "Entrada")
    despesas_operacionais = sum(f.valor for f in financeiros if f.tipo == "Saída")

    receita_total = receita_vendas + entradas_financeiras
    lucro_operacional = margem_total - despesas_operacionais

    margem_percentual = 0
    if receita_vendas > 0:
        margem_percentual = (margem_total / receita_vendas) * 100

    valor_estoque = sum(
        i.estoque_atual() * i.custo_medio_unitario()
        for i in insumos
    )

    itens_ponto_pedido = sum(
        1 for i in insumos
        if i.status_estoque() == "Ponto de pedido"
    )

    cobertura_baixa = sum(
        1 for i in insumos
        if i.status_estoque() == "Cobertura baixa"
    )

    insumos_sem_estoque = [
        i for i in insumos
        if i.estoque_atual() <= 0
    ]

    insumos_ponto_pedido = [
        i for i in insumos
        if i.status_estoque() == "Ponto de pedido"
    ]

    insumos_cobertura_baixa = [
        i for i in insumos
        if i.status_estoque() == "Cobertura baixa"
    ]

    produtos_margem_baixa = [
        p for p in produtos
        if p.percentual_margem() < 40
    ]

    return render_template(
        "dashboard.html",
        nome=session.get("usuario_nome"),
        total_insumos=len(insumos),
        total_produtos=len(produtos),
        produtos_ativos=sum(1 for p in produtos if p.ativo),
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
        produtos_margem_baixa=produtos_margem_baixa
    )
    

@app.route("/insumos", methods=["GET", "POST"])
def insumos():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        novo = Insumo(
            nome=request.form["nome"],
            unidade=request.form["unidade"],
            categoria=request.form["categoria"]
        )

        db.session.add(novo)
        db.session.commit()

        return redirect(url_for("insumos"))

    lista = Insumo.query.order_by(Insumo.nome).all()
    return render_template("insumos.html", insumos=lista)

@app.route("/entrada_estoque/<int:insumo_id>", methods=["POST"])
def entrada_estoque(insumo_id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    insumo = Insumo.query.get_or_404(insumo_id)

    entrada = MovimentacaoEstoque(
        insumo_id=insumo_id,
        tipo="Entrada",
        quantidade=float(request.form["quantidade"]),
        valor_total=float(request.form["valor_total"]),
        observacao="Compra registrada"
    )

    db.session.add(entrada)

    saida_financeira = Financeiro(
        tipo="Saída",
        categoria="Compra de insumos",
        descricao=f"Compra de {insumo.nome}",
        valor=float(request.form["valor_total"])
    )

    db.session.add(saida_financeira)
    db.session.commit()

    return redirect(url_for("insumos"))


@app.route("/excluir_insumo/<int:id>")
def excluir_insumo(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    insumo = Insumo.query.get_or_404(id)
    db.session.delete(insumo)
    db.session.commit()

    return redirect(url_for("insumos"))


@app.route("/produtos", methods=["GET", "POST"])
def produtos():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        tipo_produto = request.form["tipo_produto"]

        novo = Produto(
            nome=request.form["nome"],
            categoria=request.form["categoria"],
            preco_venda=float(request.form["preco_venda"]),
            tipo_produto=tipo_produto,
            custo_compra=float(request.form.get("custo_compra") or 0),
            estoque_produto=float(request.form.get("estoque_produto") or 0),
            ativo=True
        )

        db.session.add(novo)
        db.session.commit()

        return redirect(url_for("produtos"))

    lista = Produto.query.order_by(Produto.nome).all()
    return render_template("produtos.html", produtos=lista)

@app.route("/excluir_produto/<int:id>")
def excluir_produto(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    produto = Produto.query.get_or_404(id)
    db.session.delete(produto)
    db.session.commit()

    return redirect(url_for("produtos"))


@app.route("/alterar_status_produto/<int:id>")
def alterar_status_produto(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    produto = Produto.query.get_or_404(id)
    produto.ativo = not produto.ativo
    db.session.commit()

    return redirect(url_for("produtos"))


@app.route("/ficha_tecnica", methods=["GET", "POST"])
def ficha_tecnica():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        item = FichaTecnica(
            produto_id=int(request.form["produto_id"]),
            insumo_id=int(request.form["insumo_id"]),
            quantidade=float(request.form["quantidade"]),
            unidade_utilizada=request.form["unidade_utilizada"]
        )

        db.session.add(item)
        db.session.commit()

        return redirect(url_for("ficha_tecnica"))

    produtos = Produto.query.order_by(Produto.nome).all()
    insumos = Insumo.query.order_by(Insumo.nome).all()
    itens = FichaTecnica.query.all()

    return render_template(
        "ficha_tecnica.html",
        produtos=produtos,
        insumos=insumos,
        itens=itens
    )


@app.route("/excluir_item_ficha/<int:id>")
def excluir_item_ficha(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    item = FichaTecnica.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()

    return redirect(url_for("ficha_tecnica"))


@app.route("/vendas", methods=["GET", "POST"])
def vendas():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        produto_id = int(request.form["produto_id"])
        quantidade_vendida = int(request.form["quantidade"])

        produto = Produto.query.get_or_404(produto_id)

        if not produto.ficha_itens:
            flash("Este produto ainda não possui ficha técnica cadastrada.")
            return redirect(url_for("vendas"))

        receita_total = produto.preco_venda * quantidade_vendida
        cmv_total = produto.custo_materia_prima() * quantidade_vendida
        margem_total = receita_total - cmv_total

        venda = Venda(
            produto_id=produto.id,
            quantidade=quantidade_vendida,
            receita_total=receita_total,
            cmv_total=cmv_total,
            margem_total=margem_total
        )

        db.session.add(venda)
        db.session.flush()

        for item in produto.ficha_itens:
            quantidade_saida = item.quantidade_convertida_para_estoque() * quantidade_vendida
            custo_saida = quantidade_saida * item.insumo.custo_medio_unitario()

            saida = MovimentacaoEstoque(
                insumo_id=item.insumo_id,
                tipo="Saída",
                quantidade=quantidade_saida,
                valor_total=custo_saida,
                observacao=f"Venda de {quantidade_vendida} un. - {produto.nome}",
                venda_id=venda.id
            )

            db.session.add(saida)

        db.session.commit()

        return redirect(url_for("vendas"))

    produtos = Produto.query.filter_by(ativo=True).order_by(Produto.nome).all()
    vendas_lista = Venda.query.order_by(Venda.data.desc()).all()

    return render_template(
        "vendas.html",
        produtos=produtos,
        vendas=vendas_lista
    )


@app.route("/excluir_venda/<int:id>")
def excluir_venda(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    venda = Venda.query.get_or_404(id)
    movimentacoes = MovimentacaoEstoque.query.filter_by(venda_id=venda.id).all()

    for mov in movimentacoes:
        db.session.delete(mov)

    db.session.delete(venda)
    db.session.commit()

    return redirect(url_for("vendas"))


@app.route("/financeiro", methods=["GET", "POST"])
def financeiro():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        novo = Financeiro(
            tipo=request.form["tipo"],
            categoria=request.form["categoria"],
            descricao=request.form["descricao"],
            valor=float(request.form["valor"])
        )

        db.session.add(novo)
        db.session.commit()

        return redirect(url_for("financeiro"))

    registros = Financeiro.query.order_by(Financeiro.data.desc()).all()

    total_entradas = sum(r.valor for r in registros if r.tipo == "Entrada")
    total_saidas = sum(r.valor for r in registros if r.tipo == "Saída")
    saldo = total_entradas - total_saidas

    return render_template(
        "financeiro.html",
        registros=registros,
        total_entradas=total_entradas,
        total_saidas=total_saidas,
        saldo=saldo
    )


@app.route("/excluir_financeiro/<int:id>")
def excluir_financeiro(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    registro = Financeiro.query.get_or_404(id)
    db.session.delete(registro)
    db.session.commit()

    return redirect(url_for("financeiro"))


@app.route("/relatorios")
def relatorios():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    insumos = Insumo.query.order_by(Insumo.nome).all()
    produtos = Produto.query.order_by(Produto.nome).all()
    vendas = Venda.query.order_by(Venda.data.desc()).all()
    financeiros = Financeiro.query.order_by(Financeiro.data.desc()).all()

    receita_total = sum(v.receita_total for v in vendas)
    cmv_total = sum(v.cmv_total for v in vendas)
    margem_total = sum(v.margem_total for v in vendas)

    despesas_operacionais = sum(
        f.valor for f in financeiros
        if f.tipo == "Saída"
    )

    lucro_operacional = margem_total - despesas_operacionais

    margem_percentual = 0
    if receita_total > 0:
        margem_percentual = (margem_total / receita_total) * 100

    valor_estoque = sum(
        i.estoque_atual() * i.custo_medio_unitario()
        for i in insumos
    )

    total_vendido = sum(v.quantidade for v in vendas)

    itens_abaixo_minimo = sum(
        1 for i in insumos
        if i.estoque_atual() <= i.estoque_minimo()
    )

    itens_ponto_pedido = sum(
        1 for i in insumos
        if i.estoque_atual() > i.estoque_minimo()
        and i.estoque_atual() <= i.ponto_pedido()
    )

    coberturas = [
        i.cobertura_estoque() for i in insumos
        if i.cobertura_estoque() > 0
    ]

    cobertura_media = sum(coberturas) / len(coberturas) if coberturas else 0

    giros = [
        i.giro_estoque() for i in insumos
        if i.giro_estoque() > 0
    ]

    giro_medio = sum(giros) / len(giros) if giros else 0

    lotes = [
        i.lote_economico() for i in insumos
        if i.lote_economico() > 0
    ]

    lote_economico_medio = sum(lotes) / len(lotes) if lotes else 0

    ranking_produtos = {}

    for venda in vendas:
        nome = venda.produto.nome

        if nome not in ranking_produtos:
            ranking_produtos[nome] = {
                "quantidade": 0,
                "receita": 0,
                "cmv": 0,
                "margem": 0
            }

        ranking_produtos[nome]["quantidade"] += venda.quantidade
        ranking_produtos[nome]["receita"] += venda.receita_total
        ranking_produtos[nome]["cmv"] += venda.cmv_total
        ranking_produtos[nome]["margem"] += venda.margem_total

    ranking_produtos = sorted(
        ranking_produtos.items(),
        key=lambda item: item[1]["quantidade"],
        reverse=True
    )

    return render_template(
        "relatorios.html",
        insumos=insumos,
        produtos=produtos,
        vendas=vendas,
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
        lote_economico_medio=lote_economico_medio
    )

@app.route("/exportar_caixa")
def exportar_caixa():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    vendas = Venda.query.order_by(Venda.data.asc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Caixa"

    ws["A1"] = "ERP RESTAURANTE"
    ws["A2"] = "FECHAMENTO DE CAIXA"
    ws["A3"] = f"Data de emissão: {datetime.now().strftime('%d/%m/%Y %H:%M')}"

    ws.append([])

    ws.append([
        "Data",
        "Produto",
        "Quantidade",
        "Receita",
        "CMV",
        "Margem de Contribuição"
    ])

    receita_total = 0
    cmv_total = 0
    margem_total = 0
    quantidade_total = 0

    for venda in vendas:
        ws.append([
            venda.data.strftime("%d/%m/%Y %H:%M"),
            venda.produto.nome,
            venda.quantidade,
            venda.receita_total,
            venda.cmv_total,
            venda.margem_total
        ])

        receita_total += venda.receita_total
        cmv_total += venda.cmv_total
        margem_total += venda.margem_total
        quantidade_total += venda.quantidade

    ws.append([])
    ws.append(["RESUMO DO CAIXA"])
    ws.append(["Quantidade vendida", quantidade_total])
    ws.append(["Receita total", receita_total])
    ws.append(["CMV total", cmv_total])
    ws.append(["Margem de contribuição", margem_total])

    arquivo = io.BytesIO()
    wb.save(arquivo)
    arquivo.seek(0)

    nome_arquivo = f"Fechamento_Caixa_{datetime.now().strftime('%d-%m-%Y')}.xlsx"

    return send_file(
        arquivo,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/configuracoes")
def configuracoes():
    if "usuario_id" not in session:
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
        total_lancamentos=total_lancamentos
    )


@app.route("/fazer_backup")
def fazer_backup():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    origem = "instance/database.db"
    pasta_backup = "backups"

    if not os.path.exists(pasta_backup):
        os.makedirs(pasta_backup)

    data_hora = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destino = os.path.join(pasta_backup, f"backup_{data_hora}.db")

    if os.path.exists(origem):
        shutil.copy2(origem, destino)
        flash("Backup realizado com sucesso!")
    else:
        flash("Banco de dados não encontrado.")

    return redirect(url_for("configuracoes"))


@app.route("/alterar_senha", methods=["POST"])
def alterar_senha():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    usuario = Usuario.query.get(session["usuario_id"])

    senha_atual = request.form["senha_atual"]
    nova_senha = request.form["nova_senha"]
    confirmar = request.form["confirmar_senha"]

    if not usuario.verificar_senha(senha_atual):
        flash("Senha atual incorreta.")
        return redirect(url_for("configuracoes"))

    if nova_senha != confirmar:
        flash("As novas senhas não coincidem.")
        return redirect(url_for("configuracoes"))

    usuario.set_senha(nova_senha)
    db.session.commit()

    flash("Senha alterada com sucesso!")
    return redirect(url_for("configuracoes"))

@app.route("/editar_produto/<int:id>", methods=["POST"])
def editar_produto(id):
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    produto = Produto.query.get_or_404(id)

    produto.nome = request.form["nome"]
    produto.categoria = request.form["categoria"]
    produto.preco_venda = float(request.form["preco_venda"])
    produto.tipo_produto = request.form["tipo_produto"]
    produto.custo_compra = float(request.form.get("custo_compra") or 0)
    produto.estoque_produto = float(request.form.get("estoque_produto") or 0)

    db.session.commit()

    flash("Produto atualizado com sucesso!")
    return redirect(url_for("produtos"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

with app.app_context():
    criar_banco()

if __name__ == "__main__":
    app.run(debug=True)