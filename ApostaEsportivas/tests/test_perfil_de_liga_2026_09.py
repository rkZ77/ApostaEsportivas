"""O perfil de liga: a tabela nasce, e quem le' e' o gate de IA.

`atualizar_ligas.py` abria com `TRUNCATE TABLE league_analysis` e a tabela nao
era criada por lugar nenhum do codigo. Em PROD ela nao existia, entao o pipeline
inteiro morria com UndefinedTable; em DEV existia porque alguem a criou na mao,
e mesmo la' estava vazia. Nada no motor lia o resultado.
"""
import pytest

from services import league_analysis_service
from services.pick_engine import ai_review, league_profile_store


class _CursorFake:
    def __init__(self, linha=None, levanta=None):
        self.linha = linha
        self.levanta = levanta
        self.sqls = []

    def execute(self, sql, params=None):
        self.sqls.append(sql)
        if self.levanta:
            raise self.levanta

    def fetchone(self):
        return self.linha

    def close(self):
        pass


class TestATabelaNasce:
    def test_o_servico_sabe_criar_a_tabela(self):
        cur = _CursorFake()
        league_analysis_service.criar_tabela(cur)
        sql = " ".join(cur.sqls)
        assert "CREATE TABLE IF NOT EXISTS league_analysis" in sql
        assert "UNIQUE (league_id, season)" in sql

    def test_o_pipeline_cria_antes_de_truncar(self):
        """O TRUNCATE era a PRIMEIRA instrucao do script."""
        from pathlib import Path
        fonte = (Path(__file__).resolve().parents[1] / "src" / "atualizar_ligas.py"
                 ).read_text(encoding="utf-8")
        assert "criar_tabela(cur)" in fonte
        assert fonte.index("criar_tabela(cur)") < fonte.index("TRUNCATE TABLE league_analysis")

    def test_o_reset_nao_derruba_mais_as_outras_tabelas(self):
        """TRUNCATE de tabela inexistente derruba a instrucao INTEIRA: com
        `league_analysis` na lista, o reset nao limpava nem as outras treze."""
        from pathlib import Path
        fonte = (Path(__file__).resolve().parents[1] / "src" / "atualizar_jogos.py"
                 ).read_text(encoding="utf-8")
        bloco = fonte[fonte.index("TRUNCATE TABLE"):fonte.index("RESTART IDENTITY CASCADE")]
        assert "league_analysis" not in bloco, (
            "ela tem que sair da lista conjunta e ser limpa em separado")
        assert "TRUNCATE TABLE league_analysis RESTART IDENTITY CASCADE" in fonte


class TestQuemLe:
    def setup_method(self):
        league_profile_store.limpar_cache()

    def teardown_method(self):
        league_profile_store.limpar_cache()

    def test_o_perfil_entra_no_payload_do_gate(self):
        payload = ai_review.build_review_payload(
            [{"market_name": "x"}], "vip", {"league_id": 71},
            league_profile="Liga de muitos gols.")
        assert payload["fixture"]["league_profile"] == "Liga de muitos gols."

    def test_sem_perfil_a_chave_nem_aparece(self):
        """Chave vazia mudaria o cache_key de quem nao tem perfil."""
        payload = ai_review.build_review_payload(
            [{"market_name": "x"}], "vip", {"league_id": 71})
        assert "league_profile" not in payload["fixture"]

    def test_o_perfil_nao_vira_numero_do_motor(self):
        """Ele e' prosa; os numeros que descreve o motor le' direto do banco.

        Se algum dia ele for lido fora do gate, esta linha reprova -- e' o
        limite que separa contexto de um gate que so' VETA de termo de
        projecao.
        """
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "src"
        leitores = []
        for arquivo in src.rglob("*.py"):
            if arquivo.name in ("league_profile_store.py", "league_analysis_service.py"):
                continue
            texto = arquivo.read_text(encoding="utf-8", errors="ignore")
            # USO, nao mencao: o main.py cita o modulo num comentario da
            # migration, e comentario nao le nada.
            if ("league_profile_store.perfil" in texto
                    or "import league_profile_store" in texto):
                leitores.append(arquivo.name)
        assert leitores == ["ai_review.py"], (
            f"o perfil de liga so' pode ser lido pelo gate de IA; leitores: {leitores}")

    def test_tabela_ausente_nao_levanta(self):
        """E' o estado de todo banco onde `atualizar_ligas` nunca rodou."""
        cur = _CursorFake(levanta=RuntimeError('relation "league_analysis" does not exist'))
        assert league_profile_store.perfil_com_cursor(cur, 71, 2026) is None

    def test_texto_vazio_conta_como_ausente(self):
        cur = _CursorFake(linha=("   ",))
        assert league_profile_store.perfil_com_cursor(cur, 71, 2026) is None

    def test_le_o_texto_quando_existe(self):
        cur = _CursorFake(linha=("Liga equilibrada.",))
        assert league_profile_store.perfil_com_cursor(cur, 71, 2026) == "Liga equilibrada."

    def test_sem_liga_nao_consulta(self):
        assert league_profile_store.perfil_da_liga(None) is None
