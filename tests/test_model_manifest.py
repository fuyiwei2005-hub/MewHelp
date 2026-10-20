import json,hashlib
import pytest

def test_manifest_binds_weights_and_revision(tmp_path):
    from app.knowledge.model_manifest import write_manifest,verify_manifest
    (tmp_path/'config.json').write_text('{}')
    (tmp_path/'pytorch_model.bin').write_bytes(b'weights')
    write_manifest(tmp_path,'revision-a')
    assert verify_manifest(tmp_path,'revision-a')=='revision-a'
    with pytest.raises(ValueError):verify_manifest(tmp_path,'revision-b')
    (tmp_path/'pytorch_model.bin').write_bytes(b'changed')
    with pytest.raises(ValueError):verify_manifest(tmp_path,'revision-a')

def test_safetensors_manifest_and_mixed_weights(tmp_path):
    from app.knowledge.model_manifest import write_manifest,verify_manifest
    (tmp_path/'config.json').write_text('{}')
    (tmp_path/'model.safetensors').write_bytes(b'safe')
    write_manifest(tmp_path,'revision-safe')
    assert verify_manifest(tmp_path,'revision-safe')=='revision-safe'
    (tmp_path/'pytorch_model.bin').write_bytes(b'old')
    with pytest.raises(ValueError):verify_manifest(tmp_path,'revision-safe')
