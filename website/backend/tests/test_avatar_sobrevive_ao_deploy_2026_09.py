"""A foto de perfil não pode sumir a cada deploy.

O QUE ACONTECIA
---------------
O avatar era gravado em `static/avatars/<id>.<ext>`, DENTRO do container. O
container do Railway é efêmero: todo deploy sobe um novo e leva os arquivos
junto. Toda atualização do site apagava a foto de todo mundo, e a tela caía no
círculo de iniciais -- "sempre que tem deploy o avatar da conta sai estranho".

POR QUE NO BANCO E NÃO NUM VOLUME
---------------------------------
Volume do Railway é por AMBIENTE e é cobrado: seriam três (prod, noprod, dev)
pro mesmo problema, e dois deles continuariam quebrados até alguém lembrar. O
banco já é persistente, já tem backup e já é o mesmo em todo ambiente. Foto de
perfil é pequena (teto de 3 MB na entrada) -- é o caso em que blob em Postgres
é a resposta simples, não o cheiro.

O DISCO CONTINUA, como cache: `/static/avatars/...` é servido pelo StaticFiles
sem passar por Python. O banco é a fonte; a rota de leitura reescreve a cópia
quando ela não existe, então só o primeiro visitante depois do deploy paga uma
consulta.
"""
import inspect
import os

from routers import auth


def _front(arquivo: str) -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src")
    with open(os.path.join(base, arquivo), encoding="utf-8") as fh:
        return fh.read()


def test_a_tabela_do_avatar_existe_na_migracao():
    import migrations
    fonte = inspect.getsource(migrations)
    assert "CREATE TABLE IF NOT EXISTS user_avatars" in fonte
    assert "bytes      BYTEA NOT NULL" in fonte
    # ON DELETE CASCADE: conta apagada leva a foto junto.
    assert "REFERENCES users(id) ON DELETE CASCADE" in fonte


def test_o_upload_grava_no_banco_e_no_disco():
    fonte = inspect.getsource(auth.upload_avatar)
    assert "INSERT INTO user_avatars" in fonte
    assert "psycopg2.Binary(contents)" in fonte
    assert "dest.write_bytes(contents)" in fonte, "o cache em disco continua"
    # Reenviar troca a foto, nao cria uma segunda linha.
    assert "ON CONFLICT (user_id) DO UPDATE" in fonte


def test_a_rota_de_leitura_reescreve_o_cache():
    """Sem isso ela viraria o caminho normal de toda imagem de todo usuário, que
    é trocar um problema por outro."""
    fonte = inspect.getsource(auth.get_avatar)
    assert "SELECT ext, bytes FROM user_avatars" in fonte
    assert "write_bytes(dados)" in fonte
    assert "Cache-Control" in fonte


def test_falha_ao_escrever_o_cache_nao_derruba_a_imagem():
    """Disco cheio ou só leitura: servir continua funcionando, só não fica em
    cache. Falhar ali seria trocar uma foto por um erro."""
    fonte = inspect.getsource(auth.get_avatar)
    depois = fonte[fonte.index("write_bytes(dados)"):]
    assert "except Exception:" in depois
    assert "pass" in depois


def test_o_nome_do_arquivo_vem_de_um_inteiro():
    """O caminho é montado por concatenação · texto de fora ali abriria path
    traversal."""
    fonte = inspect.getsource(auth.get_avatar)
    assert "uid_seguro(user_id)" in fonte
    assert "return int(user_id)" in inspect.getsource(auth.uid_seguro)


def test_a_tela_tenta_o_banco_quando_o_arquivo_some():
    tela = _front("components/Avatar.tsx")
    assert "/api/auth/avatar/" in tela
    # Contador, e nao booleano: sao DUAS tentativas, e uma flag nunca chega na
    # segunda.
    assert "setTentativa" in tela
    assert "tentativa >= 2" in tela


def test_sem_rota_do_banco_vai_direto_pras_iniciais():
    """Avatar do Google nao tem segunda fonte pra tentar."""
    tela = _front("components/Avatar.tsx")
    assert "t === 0 && doBanco ? 1 : 2" in tela
