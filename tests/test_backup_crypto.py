import pytest
from ui.backup_crypto import encrypt_archive, decrypt_archive, BackupDecryptError, MAGIC_PLAIN, MAGIC_ENCRYPTED


class TestEncryptDecryptRoundTrip:
    def test_with_password(self):
        data = b'some archive bytes' * 100
        blob = encrypt_archive(data, 'correct horse battery staple')
        assert blob.startswith(MAGIC_ENCRYPTED)
        assert decrypt_archive(blob, 'correct horse battery staple') == data

    def test_without_password(self):
        data = b'some archive bytes'
        blob = encrypt_archive(data, None)
        assert blob.startswith(MAGIC_PLAIN)
        assert decrypt_archive(blob, None) == data

    def test_empty_string_password_treated_as_no_password(self):
        data = b'x'
        blob = encrypt_archive(data, '')
        assert blob.startswith(MAGIC_PLAIN)


class TestDecryptFailures:
    def test_wrong_password_raises(self):
        blob = encrypt_archive(b'secret data', 'right-password')
        with pytest.raises(BackupDecryptError):
            decrypt_archive(blob, 'wrong-password')

    def test_encrypted_without_password_raises(self):
        blob = encrypt_archive(b'secret data', 'right-password')
        with pytest.raises(BackupDecryptError):
            decrypt_archive(blob, None)

    def test_garbage_bytes_raise(self):
        with pytest.raises(BackupDecryptError):
            decrypt_archive(b'not a real backup file at all', None)

    def test_truncated_encrypted_blob_raises(self):
        blob = encrypt_archive(b'secret data', 'pw')
        with pytest.raises(BackupDecryptError):
            decrypt_archive(blob[:20], 'pw')

    def test_two_encryptions_of_same_data_differ(self):
        blob1 = encrypt_archive(b'same data', 'pw')
        blob2 = encrypt_archive(b'same data', 'pw')
        assert blob1 != blob2  # random salt/nonce each time
