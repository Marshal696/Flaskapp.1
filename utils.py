import os
import json
import base64
import sqlite3
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

MASTER_KEY = os.environ.get("MASTER_KEY")

def encrypt_data(data, key_hex):
    key_bytes = bytes.fromhex(key_hex)
    iv = os.urandom(16)
    data_str = json.dumps(data).encode('utf-8')
    pad_len = 16 - (len(data_str) % 16)
    data_str += bytes([pad_len] * pad_len)
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(data_str) + encryptor.finalize()
    result = iv + encrypted
    return base64.b64encode(result).decode('utf-8')

def decrypt_data(encrypted_b64, key_hex):
    key_bytes = bytes.fromhex(key_hex)
    data = base64.b64decode(encrypted_b64)
    iv = data[:16]
    ciphertext = data[16:]
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = decrypted_padded[-1]
    decrypted = decrypted_padded[:-pad_len]
    return json.loads(decrypted.decode('utf-8'))

def get_aes_key(uuid):
    conn = sqlite3.connect("db.sqlite")
    cursor = conn.cursor()
    cursor.execute("SELECT aes_key_encrypted FROM agents WHERE uuid = ?", (uuid,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    encrypted_key_data = row[0]
    key_data = decrypt_data(encrypted_key_data, MASTER_KEY)
    return key_data["key"]