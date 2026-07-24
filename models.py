from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import math


db = SQLAlchemy()


# =========================================================
# USUÁRIO
# =========================================================

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    usuario = db.Column(db.String(50), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def verificar_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)


# =========================================================
# INSUMO
# =========================================================

class Insumo(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    nome = db.Column(
        db.String(100),
        nullable=False
    )

    unidade = db.Column(
        db.String(20),
        nullable=False
    )

    categoria = db.Column(
        db.String(30),
        default="Matéria-prima"
    )

    # =====================================================
    # CAMPOS MANTIDOS PARA COMPATIBILIDADE COM O BANCO
    # =====================================================
    # Não serão mais preenchidos manualmente nem utilizados
    # diretamente na compra sugerida.

    demanda_mensal_estimada = db.Column(
        db.Float,
        default=0,
        nullable=False
    )

    custo_pedido = db.Column(
        db.Float,
        default=0,
        nullable=False
    )

    percentual_armazenagem = db.Column(
        db.Float,
        default=10,
        nullable=False
    )

    movimentacoes = db.relationship(
        "MovimentacaoEstoque",
        backref="insumo",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # =====================================================
    # PARÂMETROS FIXOS DO SISTEMA
    # =====================================================

    CUSTO_PEDIDO_PADRAO = 20.00

    PERCENTUAL_ARMAZENAGEM_PADRAO = 10.00

    FATOR_ESTOQUE_SEGURANCA = 0.10

    TEMPO_REPOSICAO_DIAS = 2

    CICLO_REVISAO_DIAS = 7

    PERIODO_ANALISE_DIAS = 30

    # =====================================================
    # MOVIMENTAÇÕES DE ESTOQUE
    # =====================================================

    def entradas(self):
        return sum(
            float(
                movimentacao.quantidade or 0
            )
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Entrada"
        )

    def saidas(self):
        return sum(
            float(
                movimentacao.quantidade or 0
            )
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Saída"
        )

    def estoque_atual(self):
        return (
            self.entradas()
            - self.saidas()
        )

    def valor_total_entradas(self):
        return sum(
            float(
                movimentacao.valor_total or 0
            )
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Entrada"
        )

    # =====================================================
    # CUSTO MÉDIO UNITÁRIO
    # =====================================================

    def custo_medio_unitario(self):
        quantidade_total = float(
            self.entradas() or 0
        )

        valor_total = float(
            self.valor_total_entradas() or 0
        )

        if quantidade_total <= 0:
            return 0

        if valor_total <= 0:
            return 0

        return (
            valor_total
            / quantidade_total
        )

    # =====================================================
    # CONSUMO DOS ÚLTIMOS 30 DIAS
    # =====================================================

    def consumo_ultimos_30_dias(self):
        data_limite = (
            datetime.now()
            - timedelta(
                days=self.PERIODO_ANALISE_DIAS
            )
        )

        quantidade_total = 0.0

        for movimentacao in self.movimentacoes:
            if movimentacao.tipo != "Saída":
                continue

            data_movimentacao = getattr(
                movimentacao,
                "data",
                None
            )

            if data_movimentacao is None:
                continue

            # Caso o campo esteja como Date em vez de DateTime.
            if (
                hasattr(data_movimentacao, "year")
                and not isinstance(
                    data_movimentacao,
                    datetime
                )
            ):
                data_movimentacao = datetime.combine(
                    data_movimentacao,
                    datetime.min.time()
                )

            if data_movimentacao >= data_limite:
                quantidade_total += float(
                    movimentacao.quantidade or 0
                )

        return quantidade_total

    def consumo_medio_diario(self):
        consumo_periodo = float(
            self.consumo_ultimos_30_dias() or 0
        )

        if consumo_periodo <= 0:
            return 0

        return (
            consumo_periodo
            / self.PERIODO_ANALISE_DIAS
        )

    def demanda_mensal_calculada(self):
        consumo_diario = float(
            self.consumo_medio_diario() or 0
        )

        if consumo_diario <= 0:
            return 0

        return (
            consumo_diario
            * 30
        )

    def demanda_anual_estimada(self):
        consumo_diario = float(
            self.consumo_medio_diario() or 0
        )

        if consumo_diario <= 0:
            return 0

        return (
            consumo_diario
            * 365
        )

    # =====================================================
    # ESTOQUE DE SEGURANÇA
    # =====================================================

    def estoque_seguranca(self):
        consumo_diario = float(
            self.consumo_medio_diario() or 0
        )

        if consumo_diario <= 0:
            return 0

        consumo_durante_reposicao = (
            consumo_diario
            * self.TEMPO_REPOSICAO_DIAS
        )

        return (
            consumo_durante_reposicao
            * self.FATOR_ESTOQUE_SEGURANCA
        )

    # =====================================================
    # PONTO DE PEDIDO
    # =====================================================

    def ponto_pedido(self):
        consumo_diario = float(
            self.consumo_medio_diario() or 0
        )

        if consumo_diario <= 0:
            return 0

        demanda_durante_reposicao = (
            consumo_diario
            * self.TEMPO_REPOSICAO_DIAS
        )

        return (
            demanda_durante_reposicao
            + self.estoque_seguranca()
        )

    # =====================================================
    # ESTOQUE MÍNIMO
    # =====================================================

    def estoque_minimo(self):
        return self.ponto_pedido()

    # =====================================================
    # ESTOQUE MÁXIMO — MÉTODO MIN–MAX
    # =====================================================
    # O estoque máximo cobre:
    # - o tempo de reposição;
    # - o ciclo de revisão das compras;
    # - o estoque de segurança.

    def estoque_maximo(self):
        consumo_diario = float(
            self.consumo_medio_diario() or 0
        )

        if consumo_diario <= 0:
            return 0

        dias_de_cobertura = (
            self.TEMPO_REPOSICAO_DIAS
            + self.CICLO_REVISAO_DIAS
        )

        demanda_para_cobertura = (
            consumo_diario
            * dias_de_cobertura
        )

        return (
            demanda_para_cobertura
            + self.estoque_seguranca()
        )

    # =====================================================
    # COMPRA SUGERIDA — MÉTODO MIN–MAX
    # =====================================================

    def compra_sugerida(self):
        estoque_atual = float(
            self.estoque_atual() or 0
        )

        ponto_pedido = float(
            self.ponto_pedido() or 0
        )

        estoque_maximo = float(
            self.estoque_maximo() or 0
        )

        if estoque_maximo <= 0:
            return 0

        # A compra somente é recomendada quando o saldo
        # atingir ou ficar abaixo do ponto de pedido.
        if estoque_atual <= ponto_pedido:
            quantidade = (
                estoque_maximo
                - estoque_atual
            )

            return max(
                quantidade,
                0
            )

        return 0

    # =====================================================
    # CUSTO DE ARMAZENAGEM
    # =====================================================

    def custo_armazenagem_unitario(self):
        custo_unitario = float(
            self.custo_medio_unitario() or 0
        )

        if custo_unitario <= 0:
            return 0

        return (
            custo_unitario
            * self.PERCENTUAL_ARMAZENAGEM_PADRAO
        ) / 100

    # =====================================================
    # LOTE ECONÔMICO DE COMPRA — INDICADOR
    # =====================================================
    # O LEC não determina a compra sugerida.
    # É apresentado apenas como indicador gerencial.

    def lote_economico(self):
        demanda_anual = float(
            self.demanda_anual_estimada() or 0
        )

        custo_pedido = float(
            self.CUSTO_PEDIDO_PADRAO
        )

        custo_armazenagem = float(
            self.custo_armazenagem_unitario() or 0
        )

        if demanda_anual <= 0:
            return 0

        if custo_pedido <= 0:
            return 0

        if custo_armazenagem <= 0:
            return 0

        resultado = math.sqrt(
            (
                2
                * demanda_anual
                * custo_pedido
            )
            / custo_armazenagem
        )

        return max(
            resultado,
            0
        )

    # =====================================================
    # GIRO DE ESTOQUE
    # =====================================================

    def giro_estoque(self):
        estoque_minimo = float(
            self.estoque_minimo() or 0
        )

        estoque_maximo = float(
            self.estoque_maximo() or 0
        )

        estoque_medio = (
            estoque_minimo
            + estoque_maximo
        ) / 2

        if estoque_medio <= 0:
            return 0

        consumo_periodo = float(
            self.consumo_ultimos_30_dias() or 0
        )

        if consumo_periodo <= 0:
            return 0

        return (
            consumo_periodo
            / estoque_medio
        )

    # =====================================================
    # COBERTURA DE ESTOQUE
    # =====================================================

    def cobertura_estoque(self):
        consumo_diario = float(
            self.consumo_medio_diario() or 0
        )

        estoque_atual = float(
            self.estoque_atual() or 0
        )

        if consumo_diario <= 0:
            return 0

        return (
            estoque_atual
            / consumo_diario
        )

    # Mantido para compatibilidade com rotas anteriores.
    def cobertura_dias(self):
        return self.cobertura_estoque()

    # =====================================================
    # STATUS DO ESTOQUE
    # =====================================================

    def status_estoque(self):
        estoque_atual = float(
            self.estoque_atual() or 0
        )

        ponto_pedido = float(
            self.ponto_pedido() or 0
        )

        cobertura = float(
            self.cobertura_estoque() or 0
        )

        if estoque_atual <= 0:
            return "Sem estoque"

        if (
            ponto_pedido > 0
            and estoque_atual <= ponto_pedido
        ):
            return "Ponto de pedido"

        if (
            cobertura > 0
            and cobertura <= 2
        ):
            return "Cobertura baixa"

        return "Normal"

    # =====================================================
    # AÇÃO SUGERIDA
    # =====================================================

    def acao_sugerida(self):
        estoque_atual = float(
            self.estoque_atual() or 0
        )

        ponto_pedido = float(
            self.ponto_pedido() or 0
        )

        cobertura = float(
            self.cobertura_estoque() or 0
        )

        if estoque_atual <= 0:
            return "Comprar agora"

        if (
            ponto_pedido > 0
            and estoque_atual <= ponto_pedido
        ):
            return "Comprar agora"

        if (
            cobertura > 0
            and cobertura <= 2
        ):
            return "Planejar compra"

        return "Manter estoque"
# =========================================================
# MOVIMENTAÇÃO DE ESTOQUE
# =========================================================

class MovimentacaoEstoque(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, default=datetime.now)

    insumo_id = db.Column(
        db.Integer,
        db.ForeignKey("insumo.id"),
        nullable=False
    )

    tipo = db.Column(db.String(20), nullable=False)
    quantidade = db.Column(db.Float, nullable=False)
    valor_total = db.Column(db.Float, default=0)

    observacao = db.Column(db.String(200))

    venda_id = db.Column(
        db.Integer,
        db.ForeignKey("venda.id"),
        nullable=True
    )

    def custo_unitario(self):
        if self.quantidade <= 0:
            return 0

        return self.valor_total / self.quantidade


# =========================================================
# PRODUTO
# =========================================================

class Produto(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    nome = db.Column(
        db.String(120),
        nullable=False
    )

    categoria = db.Column(
        db.String(80),
        nullable=True
    )

    preco_venda = db.Column(
        db.Float,
        default=0
    )

    ativo = db.Column(
        db.Boolean,
        default=True
    )

    tipo_produto = db.Column(
        db.String(30),
        default="Produzido"
    )

    custo_compra = db.Column(
        db.Float,
        default=0
    )

    estoque_produto = db.Column(
        db.Float,
        default=0
    )

    finalidade = db.Column(
        db.String(40),
        default="Venda"
    )

    rendimento_quantidade = db.Column(
        db.Float,
        nullable=True,
        default=1
    )

    rendimento_unidade = db.Column(
        db.String(20),
        nullable=True,
        default="un"
    )

    ficha_itens = db.relationship(
        "FichaTecnica",
        foreign_keys="FichaTecnica.produto_id",
        back_populates="produto",
        cascade="all, delete-orphan"
    )

    fichas_como_base = db.relationship(
        "FichaTecnica",
        foreign_keys="FichaTecnica.produto_base_id",
        back_populates="produto_base"
    )

    vendas = db.relationship(
        "Venda",
        back_populates="produto"
    )

    movimentacoes_produto = db.relationship(
        "MovimentacaoProduto",
        back_populates="produto",
        cascade="all, delete-orphan",
        lazy=True
    )

    def possui_ficha_tecnica(self):
        return len(self.ficha_itens) > 0

    def custo_materia_prima(
        self,
        produtos_visitados=None
    ):
        """
        Retorna o custo do produto.

        Para produto de revenda:
        utiliza o custo médio de compra.

        Para produto produzido:
        soma os custos dos componentes da ficha técnica.
        """

        if produtos_visitados is None:
            produtos_visitados = set()

        if self.id in produtos_visitados:
            return 0

        produtos_visitados = set(
            produtos_visitados
        )

        produtos_visitados.add(
            self.id
        )

        if (
            self.tipo_produto == "Revenda"
            and not self.ficha_itens
        ):
            return float(
                self.custo_compra or 0
            )

        custo_total = 0

        for item in self.ficha_itens:
            custo_total += item.custo_item(
                produtos_visitados
            )

        return custo_total

    def quantidade_convertida_para_rendimento(
        self,
        quantidade,
        unidade_utilizada
    ):
        quantidade = float(
            quantidade or 0
        )

        unidade_origem = (
            unidade_utilizada or ""
        ).strip()

        unidade_destino = (
            self.rendimento_unidade or ""
        ).strip()

        if unidade_origem == unidade_destino:
            return quantidade

        conversoes = {
            ("g", "kg"): 0.001,
            ("kg", "g"): 1000,
            ("ml", "L"): 0.001,
            ("L", "ml"): 1000,
        }

        fator = conversoes.get(
            (
                unidade_origem,
                unidade_destino
            )
        )

        if fator is None:
            raise ValueError(
                f"Não é possível converter "
                f"'{unidade_origem}' para "
                f"'{unidade_destino}'."
            )

        return quantidade * fator

    def custo_proporcional(
        self,
        quantidade,
        unidade_utilizada,
        produtos_visitados=None
    ):
        rendimento = float(
            self.rendimento_quantidade or 0
        )

        if rendimento <= 0:
            return 0

        try:
            quantidade_convertida = (
                self.quantidade_convertida_para_rendimento(
                    quantidade,
                    unidade_utilizada
                )
            )

        except ValueError:
            return 0

        custo_total_receita = (
            self.custo_materia_prima(
                produtos_visitados
            )
        )

        proporcao_utilizada = (
            quantidade_convertida
            / rendimento
        )

        return (
            custo_total_receita
            * proporcao_utilizada
        )

    def custo_por_unidade_produzida(self):
        rendimento = float(
            self.rendimento_quantidade or 0
        )

        if rendimento <= 0:
            return 0

        return (
            self.custo_materia_prima()
            / rendimento
        )

    def margem_contribuicao(self):
        preco = float(
            self.preco_venda or 0
        )

        custo = float(
            self.custo_materia_prima() or 0
        )

        return preco - custo

    def percentual_margem(self):
        preco = float(
            self.preco_venda or 0
        )

        if preco <= 0:
            return 0

        return (
            self.margem_contribuicao()
            / preco
        ) * 100

    def preco_sugerido(
        self,
        margem_desejada=40
    ):
        custo = float(
            self.custo_materia_prima() or 0
        )

        if custo <= 0:
            return 0

        percentual = float(
            margem_desejada or 0
        )

        if percentual <= 0:
            return custo

        if percentual >= 100:
            percentual = 99

        return custo / (
            1 - percentual / 100
        )

    def situacao_preco(
        self,
        margem_minima=40
    ):
        custo = float(
            self.custo_materia_prima() or 0
        )

        preco = float(
            self.preco_venda or 0
        )

        if custo <= 0:
            return "Sem custo"

        if preco <= 0:
            return "Revisar"

        if (
            self.percentual_margem()
            < margem_minima
        ):
            return "Revisar"

        return "Adequado"

# =========================================================
# MOVIMENTAÇÃO DE PRODUTO DE REVENDA
# =========================================================

class MovimentacaoProduto(db.Model):
    __tablename__ = "movimentacao_produto"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    data = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.now
    )

    produto_id = db.Column(
        db.Integer,
        db.ForeignKey("produto.id"),
        nullable=False
    )

    venda_id = db.Column(
        db.Integer,
        db.ForeignKey("venda.id"),
        nullable=True
    )

    tipo = db.Column(
        db.String(20),
        nullable=False
    )

    quantidade = db.Column(
        db.Float,
        nullable=False,
        default=0
    )

    valor_total = db.Column(
        db.Float,
        nullable=False,
        default=0
    )

    observacao = db.Column(
        db.String(255),
        nullable=True
    )

    produto = db.relationship(
        "Produto",
        back_populates="movimentacoes_produto"
    )

    venda = db.relationship(
        "Venda",
        back_populates="movimentacoes_produto"
    )

    def custo_unitario(self):
        quantidade = float(
            self.quantidade or 0
        )

        valor_total = float(
            self.valor_total or 0
        )

        if quantidade <= 0:
            return 0

        return (
            valor_total / quantidade
        )
# =========================================================
# FICHA TÉCNICA
# =========================================================

class FichaTecnica(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # Produto cuja ficha técnica está sendo montada.
    produto_id = db.Column(
        db.Integer,
        db.ForeignKey("produto.id"),
        nullable=False
    )

    # Insumo comum usado na composição.
    insumo_id = db.Column(
        db.Integer,
        db.ForeignKey("insumo.id"),
        nullable=True
    )

    # Preparo interno usado na composição.
    produto_base_id = db.Column(
        db.Integer,
        db.ForeignKey("produto.id"),
        nullable=True
    )

    quantidade = db.Column(
        db.Float,
        nullable=False
    )

    unidade_utilizada = db.Column(
        db.String(20),
        nullable=False
    )

    produto = db.relationship(
        "Produto",
        foreign_keys=[produto_id],
        back_populates="ficha_itens"
    )

    insumo = db.relationship(
        "Insumo",
        foreign_keys=[insumo_id]
    )

    produto_base = db.relationship(
        "Produto",
        foreign_keys=[produto_base_id],
        back_populates="fichas_como_base"
    )

    def nome_item(self):
        if self.insumo:
            return self.insumo.nome

        if self.produto_base:
            return self.produto_base.nome

        return "Item não informado"

    def tipo_item(self):
        if self.insumo:
            return "Insumo"

        if self.produto_base:
            return "Preparo interno"

        return "-"

    def quantidade_convertida_para_estoque(self):
        """
        Converte a quantidade usada na ficha técnica
        para a unidade de controle do estoque.
        """

        quantidade = float(
            self.quantidade or 0
        )

        if not self.insumo:
            return quantidade

        unidade_estoque = (
            self.insumo.unidade or ""
        ).strip()

        unidade_usada = (
            self.unidade_utilizada or ""
        ).strip()

        if unidade_estoque == unidade_usada:
            return quantidade

        conversoes = {
            ("g", "kg"): 0.001,
            ("kg", "g"): 1000,
            ("ml", "L"): 0.001,
            ("L", "ml"): 1000,
        }

        fator = conversoes.get(
            (
                unidade_usada,
                unidade_estoque
            )
        )

        if fator is None:
            return quantidade

        return quantidade * fator

    def custo_item(
        self,
        produtos_visitados=None
    ):
        """
        Calcula o custo deste componente.

        Insumo:
        quantidade convertida multiplicada pelo
        custo médio unitário.

        Preparo interno:
        custo proporcional ao rendimento.
        """

        if self.insumo:
            quantidade_convertida = (
                self.quantidade_convertida_para_estoque()
            )

            custo_unitario = float(
                self.insumo.custo_medio_unitario()
                or 0
            )

            return (
                quantidade_convertida
                * custo_unitario
            )

        if self.produto_base:
            return self.produto_base.custo_proporcional(
                quantidade=self.quantidade,
                unidade_utilizada=(
                    self.unidade_utilizada
                ),
                produtos_visitados=(
                    produtos_visitados
                )
            )

        return 0.0


# =========================================================
# VENDA
# =========================================================

class Venda(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    data = db.Column(
        db.DateTime,
        default=datetime.now
    )

    produto_id = db.Column(
        db.Integer,
        db.ForeignKey("produto.id"),
        nullable=False
    )

    quantidade = db.Column(
        db.Integer,
        nullable=False
    )

    receita_total = db.Column(
        db.Float,
        default=0
    )

    cmv_total = db.Column(
        db.Float,
        default=0
    )

    margem_total = db.Column(
        db.Float,
        default=0
    )

    movimentou_estoque = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    produto = db.relationship(
        "Produto",
        back_populates="vendas"
    )

    movimentacoes = db.relationship(
        "MovimentacaoEstoque",
        backref="venda",
        lazy=True
    )

        # Movimentações de produtos de revenda relacionadas à venda
    movimentacoes_produto = db.relationship(
        "MovimentacaoProduto",
        back_populates="venda",
        lazy=True,
    )

    def margem_percentual(self):
        receita = float(
            self.receita_total or 0
        )

        margem = float(
            self.margem_total or 0
        )

        if receita <= 0:
            return 0.0

        return (
            margem / receita
        ) * 100
# =========================================================
# FINANCEIRO
# =========================================================

class Financeiro(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    data = db.Column(
        db.DateTime,
        default=datetime.now
    )

    tipo = db.Column(
        db.String(20),
        nullable=False
    )

    categoria = db.Column(
        db.String(50),
        nullable=False
    )

    descricao = db.Column(
        db.String(150),
        nullable=False
    )

    valor = db.Column(
        db.Float,
        nullable=False
    )

class MovimentacaoProduto(db.Model):
    """
    Registra as entradas, saídas e ajustes de estoque
    dos produtos classificados como Revenda.

    Exemplos:
    - Entrada: compra de refrigerantes ou cervejas;
    - Saída: venda de um produto de revenda;
    - Ajuste: correção administrativa do estoque.
    """

    __tablename__ = "movimentacao_produto"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    data = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.now,
    )

    produto_id = db.Column(
        db.Integer,
        db.ForeignKey("produto.id"),
        nullable=False,
    )

    tipo = db.Column(
        db.String(20),
        nullable=False,
    )

    quantidade = db.Column(
        db.Float,
        nullable=False,
        default=0,
    )

    valor_total = db.Column(
        db.Float,
        nullable=False,
        default=0,
    )

    observacao = db.Column(
        db.String(255),
        nullable=True,
    )

    venda_id = db.Column(
        db.Integer,
        db.ForeignKey("venda.id"),
        nullable=True,
    )

    produto = db.relationship(
        "Produto",
        back_populates="movimentacoes_produto",
    )

    venda = db.relationship(
        "Venda",
        back_populates="movimentacoes_produto",
    )

    def custo_unitario(self):
        """
        Retorna o custo unitário da movimentação.

        O cálculo é realizado principalmente nas entradas
        provenientes das compras dos produtos de revenda.
        """

        quantidade = float(
            self.quantidade or 0
        )

        valor_total = float(
            self.valor_total or 0
        )

        if quantidade <= 0:
            return 0.0

        return valor_total / quantidade

    def __repr__(self):
        return (
            f"<MovimentacaoProduto "
            f"{self.tipo} - "
            f"Produto {self.produto_id} - "
            f"{self.quantidade}>"
        )