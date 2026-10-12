import base64
import hashlib
import re

from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.crypto import constant_time_compare


class GnuboardPBKDF2SHA256PasswordHasher(BasePasswordHasher):
    algorithm = "gnu_pbkdf2_sha256"

    def encode(self, password, salt, iterations=12000):
        iterations = int(iterations)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt.encode(),
            iterations,
            dklen=24,
        )
        checksum = base64.b64encode(digest).decode("ascii")
        return "%s$%d$%s$%s" % (self.algorithm, iterations, salt, checksum)

    def verify(self, password, encoded):
        algorithm, iterations, salt, checksum = encoded.split("$", 3)
        if algorithm != self.algorithm:
            return False
        encoded_2 = self.encode(password, salt, iterations)
        return constant_time_compare(encoded, encoded_2)

    def safe_summary(self, encoded):
        algorithm, iterations, salt, checksum = encoded.split("$", 3)
        return {
            "algorithm": algorithm,
            "iterations": iterations,
            "salt": mask_hash(salt),
            "hash": mask_hash(checksum),
        }

    def must_update(self, encoded):
        return True

    def harden_runtime(self, password, encoded):
        pass


class GnuboardMySQLPasswordHasher(BasePasswordHasher):
    algorithm = "gnu_mysql_password"

    def encode(self, password, salt=""):
        first = hashlib.sha1(password.encode()).digest()
        checksum = "*" + hashlib.sha1(first).hexdigest().upper()
        return "%s$%s" % (self.algorithm, checksum)

    def verify(self, password, encoded):
        algorithm, checksum = encoded.split("$", 1)
        if algorithm != self.algorithm:
            return False
        return constant_time_compare(checksum.upper(), self.encode(password).split("$", 1)[1])

    def safe_summary(self, encoded):
        algorithm, checksum = encoded.split("$", 1)
        return {"algorithm": algorithm, "hash": mask_hash(checksum)}

    def must_update(self, encoded):
        return True

    def harden_runtime(self, password, encoded):
        pass


class GnuboardMySQLOldPasswordHasher(BasePasswordHasher):
    algorithm = "gnu_mysql_old_password"

    def encode(self, password, salt=""):
        nr = 1345345333
        add = 7
        nr2 = 0x12345671
        for char in password:
            if char in (" ", "\t"):
                continue
            value = ord(char)
            nr ^= (((nr & 63) + add) * value) + (nr << 8)
            nr2 += (nr2 << 8) ^ nr
            add += value
            nr &= 0x7FFFFFFF
            nr2 &= 0x7FFFFFFF
        return "%s$%08x%08x" % (self.algorithm, nr, nr2)

    def verify(self, password, encoded):
        algorithm, checksum = encoded.split("$", 1)
        if algorithm != self.algorithm:
            return False
        return constant_time_compare(checksum.lower(), self.encode(password).split("$", 1)[1])

    def safe_summary(self, encoded):
        algorithm, checksum = encoded.split("$", 1)
        return {"algorithm": algorithm, "hash": mask_hash(checksum)}

    def must_update(self, encoded):
        return True

    def harden_runtime(self, password, encoded):
        pass


def convert_gnuboard_password_hash(raw_hash):
    raw_hash = str(raw_hash or "").strip()
    if not raw_hash:
        return None

    parts = raw_hash.split(":")
    if len(parts) == 4 and parts[0].lower() == "sha256":
        return "gnu_pbkdf2_sha256$%s$%s$%s" % (parts[1], parts[2], parts[3])

    if raw_hash.startswith("*") and len(raw_hash) == 41:
        return "gnu_mysql_password$%s" % raw_hash.upper()

    if re.fullmatch(r"[0-9a-fA-F]{16}", raw_hash):
        return "gnu_mysql_old_password$%s" % raw_hash.lower()

    return None
