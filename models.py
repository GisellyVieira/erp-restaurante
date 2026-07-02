from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import math

db = SQLAlchemy()


class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    usuario = db.Column(db.String(50), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)

    def set_senha(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def verificar_senha(self, senha):
        return check_password_hash(self.senha_hash, senha)

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
        return sum(m.quantidade for m in self.movimentacoes if m.tipo == "Entrada")

    def saidas(self):
        return sum(m.quantidade for m in self.movimentacoes if m.tipo == "Saída")

    def estoque_atual(self):
        return self.entradas() - self.saidas()

    def valor_total_entradas(self):
        return sum(m.valor_total for m in self.movimentacoes if m.tipo == "Entrada")

    def custo_medio_unitario(self):
        entradas = self.entradas()
        if entradas <= 0:
            return 0
        return self.valor_total_entradas() / entradas

    def consumo_medio_diario(self):
        saidas = [m for m in self.movimentacoes if m.tipo == "Saída"]
        if not saidas:
            return 0
        return sum(m.quantidade for m in saidas) / 30

    def estoque_seguranca(self):
        consumo = self.consumo_medio_diario()
        if consumo <= 0:
            return 0

        z = 1.65
        desvio_estimado = consumo * 0.30
        lead_time_padrao = 2

        return z * desvio_estimado * math.sqrt(lead_time_padrao)

    def ponto_pedido(self):
        consumo = self.consumo_medio_diario()
        lead_time_padrao = 2
        return (consumo * lead_time_padrao) + self.estoque_seguranca()

    def cobertura_estoque(self):
        consumo = self.consumo_medio_diario()
        if consumo <= 0:
            return 0
        return self.estoque_atual() / consumo

    def status_estoque(self):
        if self.estoque_atual() <= 0:
            return "Sem estoque"
        if self.estoque_atual() <= self.ponto_pedido():
            return "Ponto de pedido"
        if self.cobertura_estoque() <= 2:
            return "Cobertura baixa"
        return "Normal"

class MovimentacaoEstoque(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, default=datetime.now)

    insumo_id = db.Column(db.Integer, db.ForeignKey("insumo.id"), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)

    quantidade = db.Column(db.Float, nullable=False)
    valor_total = db.Column(db.Float, default=0)

    observacao = db.Column(db.String(200))
    venda_id = db.Column(db.Integer, db.ForeignKey("venda.id"), nullable=True)

    def custo_unitario(self):
        if self.quantidade <= 0:
            return 0
        return self.valor_total / self.quantidade
    
class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    preco_venda = db.Column(db.Float, nullable=False)
    ativo = db.Column(db.Boolean, default=True)

    tipo_produto = db.Column(db.String(30), default="Produzido")
    custo_compra = db.Column(db.Float, default=0)
    estoque_produto = db.Column(db.Float, default=0)

    ficha_itens = db.relationship(
        "FichaTecnica",
        backref="produto",
        lazy=True,
        cascade="all, delete-orphan"
    )

    vendas = db.relationship(
        "Venda",
        backref="produto",
        lazy=True
    )

    def custo_materia_prima(self):
        if self.tipo_produto == "Revenda":
            return self.custo_compra
        return sum(item.custo_item() for item in self.ficha_itens)

    def margem_contribuicao(self):
        return self.preco_venda - self.custo_materia_prima()

    def percentual_margem(self):
        if self.preco_venda <= 0:
            return 0
        return (self.margem_contribuicao() / self.preco_venda) * 100

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


class FichaTecnica(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    produto_id = db.Column(db.Integer, db.ForeignKey("produto.id"), nullable=False)
    insumo_id = db.Column(db.Integer, db.ForeignKey("insumo.id"), nullable=False)

    quantidade = db.Column(db.Float, nullable=False)
    unidade_utilizada = db.Column(db.String(20), nullable=False)

    insumo = db.relationship("Insumo")

    def quantidade_convertida_para_estoque(self):
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
        quantidade_convertida = self.quantidade_convertida_para_estoque()
        custo_unitario = self.insumo.custo_medio_unitario()
        return quantidade_convertida * custo_unitario


class Venda(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, default=datetime.now)

    produto_id = db.Column(db.Integer, db.ForeignKey("produto.id"), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)

    receita_total = db.Column(db.Float, default=0)
    cmv_total = db.Column(db.Float, default=0)
    margem_total = db.Column(db.Float, default=0)

    movimentacoes = db.relationship(
        "MovimentacaoEstoque",
        backref="venda",
        lazy=True
    )

    def margem_percentual(self):
        if self.receita_total <= 0:
            return 0
        return (self.margem_total / self.receita_total) * 100


class Financeiro(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.DateTime, default=datetime.now)

    tipo = db.Column(db.String(20), nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    descricao = db.Column(db.String(150), nullable=False)
    valor = db.Column(db.Float, nullable=False)