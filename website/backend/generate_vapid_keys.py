"""
Gera um par de chaves VAPID para push notifications.
Rode uma vez: python generate_vapid_keys.py
Adicione as variaveis de saida no Railway (ambiente do backend).
"""
from cryptography.hazmat.primitives.asymmetric import ec
import base64

key  = ec.generate_private_key(ec.SECP256R1())
nums = key.private_numbers()

priv_bytes = nums.private_value.to_bytes(32, 'big')
pub_nums   = key.public_key().public_numbers()
pub_bytes  = b'\x04' + pub_nums.x.to_bytes(32, 'big') + pub_nums.y.to_bytes(32, 'big')

priv_b64 = base64.urlsafe_b64encode(priv_bytes).rstrip(b'=').decode()
pub_b64  = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()

print("Adicione no Railway (backend):")
print()
print(f"VAPID_PRIVATE_KEY={priv_b64}")
print(f"VAPID_PUBLIC_KEY={pub_b64}")
print()
print("Nao compartilhe a VAPID_PRIVATE_KEY.")
