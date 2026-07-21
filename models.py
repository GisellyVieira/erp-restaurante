from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
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
    # DADOS PARA O LOTE ECONÔMICO DE COMPRA — LEC
    # =====================================================

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
    # MOVIMENTAÇÕES
    # =====================================================

    def entradas(self):
        return sum(
            float(movimentacao.quantidade or 0)
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Entrada"
        )

    def saidas(self):
        return sum(
            float(movimentacao.quantidade or 0)
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Saída"
        )

    def estoque_atual(self):
        return self.entradas() - self.saidas()

    def valor_total_entradas(self):
        return sum(
            float(movimentacao.valor_total or 0)
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Entrada"
        )

    # =====================================================
    # CUSTO MÉDIO
    # =====================================================

    def custo_medio_unitario(self):
        entradas = self.entradas()

        if entradas <= 0:
            return 0

        return (
            self.valor_total_entradas()
            / entradas
        )

    # =====================================================
    # CONSUMO E ESTOQUE DE SEGURANÇA
    # =====================================================

    def consumo_medio_diario(self):
        saidas = [
            movimentacao
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Saída"
        ]

        if not saidas:
            return 0

        quantidade_total = sum(
            float(movimentacao.quantidade or 0)
            for movimentacao in saidas
        )

        return quantidade_total / 30

    def estoque_seguranca(self):
        return (
            self.consumo_medio_diario()
            * 0.10
        )

    def ponto_pedido(self):
        consumo = self.consumo_medio_diario()

        # Tempo médio de reposição considerado:
        # 2 dias.
        tempo_reposicao = 2

        return (
            consumo * tempo_reposicao
        ) + self.estoque_seguranca()

    def estoque_minimo(self):
        return self.ponto_pedido()

    # =====================================================
    # LOTE ECONÔMICO DE COMPRA — LEC
    # =====================================================

    def custo_armazenagem_unitario(self):
        custo_unitario = float(
            self.custo_medio_unitario() or 0
        )

        percentual = float(
            self.percentual_armazenagem or 0
        )

        if custo_unitario <= 0:
            return 0

        if percentual <= 0:
            return 0

        return (
            custo_unitario
            * percentual
        ) / 100

    def lote_economico(self):
        demanda = float(
            self.demanda_mensal_estimada or 0
        )

        custo_pedido = float(
            self.custo_pedido or 0
        )

        custo_armazenagem = float(
            self.custo_armazenagem_unitario() or 0
        )

        if demanda <= 0:
            return 0

        if custo_pedido <= 0:
            return 0

        if custo_armazenagem <= 0:
            return 0

        return math.sqrt(
            (
                2
                * demanda
                * custo_pedido
            )
            / custo_armazenagem
        )

    def estoque_maximo(self):
        return (
            self.estoque_minimo()
            + self.lote_economico()
        )

    # =====================================================
    # INDICADORES DE ESTOQUE
    # =====================================================

    def giro_estoque(self):
        estoque_medio = (
            self.estoque_minimo()
            + self.estoque_maximo()
        ) / 2

        if estoque_medio <= 0:
            return 0

        return (
            self.saidas()
            / estoque_medio
        )

    def cobertura_estoque(self):
        consumo = self.consumo_medio_diario()

        if consumo <= 0:
            return 0

        return (
            self.estoque_atual()
            / consumo
        )

    # =====================================================
    # STATUS E AÇÃO SUGERIDA
    # =====================================================

    def acao_sugerida(self):
        estoque = self.estoque_atual()

        if estoque <= 0:
            return "Comprar agora"

        if estoque <= self.estoque_minimo():
            return "Comprar agora"

        if estoque <= self.ponto_pedido():
            return "Planejar compra"

        return "Manter estoque"

    def status_estoque(self):
        estoque = self.estoque_atual()

        if estoque <= 0:
            return "Sem estoque"

        if estoque <= self.estoque_minimo():
            return "Abaixo do mínimo"

        if estoque <= self.ponto_pedido():
            return "Ponto de pedido"

        if self.cobertura_estoque() <= 2:
            return "Cobertura baixa"

        return "Normal"
    
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

    # Rendimento total da receita.
    # Exemplo: o vinagrete rende 2 kg.
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

    # Itens usados para produzir este produto.
    ficha_itens = db.relationship(
        "FichaTecnica",
        foreign_keys="FichaTecnica.produto_id",
        back_populates="produto",
        cascade="all, delete-orphan"
    )

    # Fichas em que este produto aparece
    # como preparo interno.
    fichas_como_base = db.relationship(
        "FichaTecnica",
        foreign_keys="FichaTecnica.produto_base_id",
        back_populates="produto_base"
    )

    # Vendas registradas deste produto.
    vendas = db.relationship(
        "Venda",
        back_populates="produto"
    )

    def possui_ficha_tecnica(self):
        return len(self.ficha_itens) > 0

    def custo_materia_prima(
        self,
        produtos_visitados=None
    ):
        """
        Calcula o custo total do produto.

        Produto de revenda:
        utiliza o custo de compra.

        Produto produzido:
        soma os custos dos itens da ficha técnica.
        """

        if produtos_visitados is None:
            produtos_visitados = set()

        # Evita referência circular entre produtos.
        if self.id in produtos_visitados:
            return 0.0

        produtos_visitados = set(
            produtos_visitados
        )

        produtos_visitados.add(self.id)

        # Para produto de revenda, utiliza
        # diretamente o custo de compra.
        if self.tipo_produto == "Revenda":
            return float(
                self.custo_compra or 0
            )

        custo_total = 0.0

        for item in self.ficha_itens:
            custo_item = item.custo_item(
                produtos_visitados
            )

            custo_total += float(
                custo_item or 0
            )

        return custo_total

    def quantidade_convertida_para_rendimento(
        self,
        quantidade,
        unidade_utilizada
    ):
        """
        Converte a quantidade utilizada para a unidade
        em que o rendimento do preparo foi cadastrado.
        """

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
        """
        Calcula o custo proporcional da quantidade
        utilizada de um preparo interno.

        Exemplo:
        receita custa R$ 20,00 e rende 2 kg;
        utilização de 50 g;
        custo proporcional de R$ 0,50.
        """

        rendimento = float(
            self.rendimento_quantidade or 0
        )

        if rendimento <= 0:
            return 0.0

        try:
            quantidade_convertida = (
                self.quantidade_convertida_para_rendimento(
                    quantidade,
                    unidade_utilizada
                )
            )

        except ValueError:
            return 0.0

        custo_total_receita = float(
            self.custo_materia_prima(
                produtos_visitados
            ) or 0
        )

        proporcao_utilizada = (
            quantidade_convertida / rendimento
        )

        return (
            custo_total_receita
            * proporcao_utilizada
        )

    def custo_por_unidade_produzida(self):
        """
        Retorna o custo por unidade de rendimento.

        Exemplos:
        custo por kg, litro ou unidade.
        """

        rendimento = float(
            self.rendimento_quantidade or 0
        )

        if rendimento <= 0:
            return 0.0

        custo_total = float(
            self.custo_materia_prima() or 0
        )

        return custo_total / rendimento

    def margem_contribuicao(self):
        """
        Calcula a diferença entre o preço de venda
        e o custo do produto.
        """

        preco = float(
            self.preco_venda or 0
        )

        custo = float(
            self.custo_materia_prima() or 0
        )

        return preco - custo

    def percentual_margem(self):
        """
        Calcula o percentual de margem em relação
        ao preço de venda.
        """

        preco = float(
            self.preco_venda or 0
        )

        if preco <= 0:
            return 0.0

        margem = float(
            self.margem_contribuicao() or 0
        )

        return (
            margem / preco
        ) * 100

    def preco_sugerido(
        self,
        margem_desejada=40
    ):
        """
        Calcula o preço necessário para alcançar
        a margem desejada.

        A margem padrão é de 40%.
        """

        custo = float(
            self.custo_materia_prima() or 0
        )

        if custo <= 0:
            return 0.0

        margem = float(
            margem_desejada or 0
        )

        if margem <= 0:
            return custo

        if margem >= 100:
            margem = 99

        divisor = 1 - (
            margem / 100
        )

        if divisor <= 0:
            return 0.0

        return custo / divisor

    def situacao_preco(
        self,
        margem_minima=40
    ):
        """
        Classifica a situação do preço do produto.

        Possíveis resultados:
        - Sem custo
        - Revisar
        - Adequado
        """

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

        margem = float(
            self.percentual_margem() or 0
        )

        if margem < margem_minima:
            return "Revisar"

        return "Adequado"


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

    produto = db.relationship(
        "Produto",
        back_populates="vendas"
    )

    movimentacoes = db.relationship(
        "MovimentacaoEstoque",
        backref="venda",
        lazy=True
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