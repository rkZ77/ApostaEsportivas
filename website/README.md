# ApostaSmart — Website

## Estrutura
```
website/
├── backend/    FastAPI + JWT + PostgreSQL
└── frontend/   React + Vite + Tailwind
```

## Setup Backend

```bash
cd website/backend

# Criar venv
python -m venv venv
venv\Scripts\activate      # Windows

pip install -r requirements.txt

# Rodar migration (cria tabela users)
# Execute o SQL em db/migration_users.sql no seu banco

# Criar primeiro admin (via psql ou DBeaver):
# INSERT INTO users (name, email, password_hash, plan)
# VALUES ('Admin', 'admin@email.com', '<bcrypt_hash>', 'admin');

# Iniciar servidor
uvicorn main:app --reload --port 8000
```

## Setup Frontend

```bash
cd website/frontend

npm install
npm run dev      # http://localhost:5173
```

## Variáveis de ambiente
O backend reutiliza o `.env` do bot (DB_HOST, DB_PORT, etc).
Adicione ao .env se quiser customizar o JWT:
```
JWT_SECRET=sua-chave-secreta-aqui
```

## Criar admin pelo Python
```python
from passlib.context import CryptContext
pwd = CryptContext(schemes=["bcrypt"])
print(pwd.hash("sua_senha"))
# Cole o hash no INSERT acima
```

## Deploy (mesmo servidor)
- Backend: `uvicorn main:app --host 0.0.0.0 --port 8000`
- Frontend: `npm run build` → servir `/dist` via nginx
