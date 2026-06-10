from database import get_connection
conn = get_connection(); cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' ORDER BY ordinal_position")
print("users:", [r['column_name'] for r in cur.fetchall()])
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='ai_suggestions' ORDER BY ordinal_position")
print("ai_suggestions:", [r['column_name'] for r in cur.fetchall()])

# Verifica se anthropic está instalado
try:
    import anthropic; print("anthropic SDK:", anthropic.__version__)
except ImportError:
    print("anthropic SDK: NAO INSTALADO")

# Verifica se mercadopago está instalado
try:
    import mercadopago; print("mercadopago SDK: instalado")
except ImportError:
    print("mercadopago SDK: NAO INSTALADO")

cur.close(); conn.close()
