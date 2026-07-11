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
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    unidade = db.Column(db.String(20), nullable=False)
    categoria = db.Column(db.String(30), default="Matéria-prima")

    movimentacoes = db.relationship(
        "MovimentacaoEstoque",
        backref="insumo",
        lazy=True,
        cascade="all, delete-orphan"
    )

    def entradas(self):
        return sum(
            movimentacao.quantidade
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Entrada"
        )

    def saidas(self):
        return sum(
            movimentacao.quantidade
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Saída"
        )

    def estoque_atual(self):
        return self.entradas() - self.saidas()

    def valor_total_entradas(self):
        return sum(
            movimentacao.valor_total
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Entrada"
        )

    def custo_medio_unitario(self):
        entradas = self.entradas()

        if entradas <= 0:
            return 0

        return self.valor_total_entradas() / entradas

    def consumo_medio_diario(self):
        saidas = [
            movimentacao
            for movimentacao in self.movimentacoes
            if movimentacao.tipo == "Saída"
        ]

        if not saidas:
            return 0

        return sum(
            movimentacao.quantidade
            for movimentacao in saidas
        ) / 30

    def estoque_seguranca(self):
        return self.consumo_medio_diario() * 0.10

    def ponto_pedido(self):
        consumo = self.consumo_medio_diario()
        tempo_reposicao = 2

        return (
            consumo * tempo_reposicao
        ) + self.estoque_seguranca()

    def estoque_minimo(self):
        return self.ponto_pedido()

    def lote_economico(self):
        demanda = self.saidas()
        custo_pedido = 20
        custo_armazenagem = self.custo_medio_unitario()

        if demanda <= 0 or custo_armazenagem <= 0:
            return 0

        return math.sqrt(
            (2 * demanda * custo_pedido) / custo_armazenagem
        )

    def estoque_maximo(self):
        return self.estoque_minimo() + self.lote_economico()

    def giro_estoque(self):
        estoque_medio = (
            self.estoque_minimo() + self.estoque_maximo()
        ) / 2

        if estoque_medio <= 0:
            return 0

        return self.saidas() / estoque_medio

    def cobertura_estoque(self):
        consumo = self.consumo_medio_diario()

        if consumo <= 0:
            return 0

        return self.estoque_atual() / consumo

    def acao_sugerida(self):
        if self.estoque_atual() <= 0:
            return "Comprar agora"

        if self.estoque_atual() <= self.estoque_minimo():
            return "Comprar agora"

        if self.estoque_atual() <= self.ponto_pedido():
            return "Planejar compra"

        return "Manter estoque"

    def status_estoque(self):
        if self.estoque_atual() <= 0:
            return "Sem estoque"

        if self.estoque_atual() <= self.estoque_minimo():
            return "Abaixo do mínimo"

        if self.estoque_atual() <= self.ponto_pedido():
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

class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    preco_venda = db.Column(db.Float, nullable=False)
    ativo = db.Column(db.Boolean, default=True)

    tipo_produto = db.Column(
        db.String(30),
        default="Produzido"
    )

    custo_compra = db.Column(db.Float, default=0)
    estoque_produto = db.Column(db.Float, default=0)

    # Itens que formam a ficha técnica deste produto.
    ficha_itens = db.relationship(
        "FichaTecnica",
        foreign_keys="FichaTecnica.produto_id",
        back_populates="produto",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # Fichas técnicas nas quais este produto aparece como base.
    fichas_como_base = db.relationship(
        "FichaTecnica",
        foreign_keys="FichaTecnica.produto_base_id",
        back_populates="produto_base",
        lazy=True
    )

    vendas = db.relationship(
        "Venda",
        backref="produto",
        lazy=True
    )

    def custo_materia_prima(self):
        if self.tipo_produto == "Revenda":
            return self.custo_compra or 0

        return sum(
            item.custo_item()
            for item in self.ficha_itens
        )

    def margem_contribuicao(self):
        return self.preco_venda - self.custo_materia_prima()

    def percentual_margem(self):
        if self.preco_venda <= 0:
            return 0

        return (
            self.margem_contribuicao() / self.preco_venda
        ) * 100

    def preco_sugerido(self):
        custo = self.custo_materia_prima()
        margem_desejada = 0.60

        if custo <= 0:
            return 0

        return custo / (1 - margem_desejada)

    def situacao_preco(self):
        sugerido = self.preco_sugerido()

        if sugerido <= 0:
            return "Sem custo"

        if self.preco_venda < sugerido:
            return "Revisar"

        return "Adequado"


# =========================================================
# FICHA TÉCNICA
# =========================================================

class FichaTecnica(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # Produto cuja ficha técnica está sendo montada.
    produto_id = db.Column(
        db.Integer,
        db.ForeignKey("produto.id"),
        nullable=False
    )

    # Insumo comum usado na receita.
    insumo_id = db.Column(
        db.Integer,
        db.ForeignKey("insumo.id"),
        nullable=True
    )

    # Produto produzido internamente usado como base.
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
        # Produtos-base não usam a conversão do estoque de insumos.
        if not self.insumo:
            return self.quantidade

        unidade_estoque = self.insumo.unidade
        unidade_usada = self.unidade_utilizada

        if unidade_estoque == "kg" and unidade_usada == "g":
            return self.quantidade / 1000

        if unidade_estoque == "g" and unidade_usada == "kg":
            return self.quantidade * 1000

        if unidade_estoque == "L" and unidade_usada == "ml":
            return self.quantidade / 1000

        if unidade_estoque == "ml" and unidade_usada == "L":
            return self.quantidade * 1000

        return self.quantidade

    def custo_item(self):
        # Custo de um insumo comum.
        if self.insumo:
            quantidade_convertida = (
                self.quantidade_convertida_para_estoque()
            )

            custo_unitario = (
                self.insumo.custo_medio_unitario()
            )

            return quantidade_convertida * custo_unitario

        # Custo de um produto produzido internamente.
        if self.produto_base:
            custo_produto_base = (
                self.produto_base.custo_materia_prima()
            )

            return self.quantidade * custo_produto_base

        return 0


# =========================================================
# VENDA
# =========================================================

class Venda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, default=datetime.now)

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

    movimentacoes = db.relationship(
        "MovimentacaoEstoque",
        backref="venda",
        lazy=True
    )

    def margem_percentual(self):
        if self.receita_total <= 0:
            return 0

        return (
            self.margem_total / self.receita_total
        ) * 100


# =========================================================
# FINANCEIRO
# =========================================================

class Financeiro(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, default=datetime.now)

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