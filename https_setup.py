from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


BASE_DIR = Path(__file__).resolve().parent
CERT_DIR = BASE_DIR / "certs"
CA_CERT_PEM = CERT_DIR / "kohs-local-ca.pem"
CA_CERT_DER = CERT_DIR / "kohs-local-ca.cer"
CA_KEY_PEM = CERT_DIR / "kohs-local-ca-key.pem"
CERT_PEM = CERT_DIR / "localhost.pem"
CERT_DER = CERT_DIR / "localhost.cer"
KEY_PEM = CERT_DIR / "localhost-key.pem"


def _write_private_key(path: Path, private_key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _load_or_create_ca(now: datetime) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    if CA_KEY_PEM.exists() and CA_CERT_PEM.exists():
        private_key = serialization.load_pem_private_key(CA_KEY_PEM.read_bytes(), password=None)
        certificate = x509.load_pem_x509_certificate(CA_CERT_PEM.read_bytes())
        if isinstance(private_key, rsa.RSAPrivateKey) and certificate.not_valid_after_utc > now + timedelta(days=30):
            CA_CERT_DER.write_bytes(certificate.public_bytes(serialization.Encoding.DER))
            return private_key, certificate

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "KoH Spotify Lyrics"),
            x509.NameAttribute(NameOID.COMMON_NAME, "KoH Spotify Lyrics Local CA"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()), critical=False)
        .sign(private_key=private_key, algorithm=hashes.SHA256())
    )
    _write_private_key(CA_KEY_PEM, private_key)
    CA_CERT_PEM.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    CA_CERT_DER.write_bytes(certificate.public_bytes(serialization.Encoding.DER))
    return private_key, certificate


def create_localhost_certificate() -> None:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ca_key, ca_certificate = _load_or_create_ca(now)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "KoH Spotify Lyrics"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_certificate.subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=397))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.IPAddress(ipaddress.ip_address("::1")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )

    _write_private_key(KEY_PEM, private_key)
    CERT_PEM.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    CERT_DER.write_bytes(certificate.public_bytes(serialization.Encoding.DER))
    print(f"CA SHA256: {ca_certificate.fingerprint(hashes.SHA256()).hex().upper()}")
    print(f"Servidor SHA256: {certificate.fingerprint(hashes.SHA256()).hex().upper()}")


if __name__ == "__main__":
    create_localhost_certificate()
