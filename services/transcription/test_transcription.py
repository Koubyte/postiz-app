"""Test decoder bounds and waveform input without downloading a model."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

@pytest.fixture
def speech(monkeypatch):
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=lambda *a,**kw:None))
    spec=importlib.util.spec_from_file_location('speech_test_app',Path(__file__).with_name('app.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def test_decoder_passes_float_waveform_directly_to_whisper(speech,monkeypatch):
    raw=np.array([0,32767,-32768],dtype='<i2').tobytes();calls=[]
    monkeypatch.setattr(speech.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=raw))
    def transcribe(audio,**kwargs):
        calls.append((audio,kwargs));return [SimpleNamespace(text=' Deux posts, sans prix. ')],None
    speech.model=SimpleNamespace(transcribe=transcribe)
    speech.lock.acquire()
    assert speech.recognize(b'encoded audio')=={'text':'Deux posts, sans prix.'}
    audio,kwargs=calls[0]
    assert audio.dtype==np.float32 and audio[2]==-1 and kwargs['language']=='fr'
    assert not speech.lock.locked()

@pytest.mark.parametrize('result',[(1,b'bad'),(0,b''),(0,b'\0'*(181*16000*2))])
def test_invalid_or_overlong_audio_releases_lock(speech,monkeypatch,result):
    code,raw=result
    monkeypatch.setattr(speech.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=code,stdout=raw))
    speech.lock.acquire()
    with pytest.raises(HTTPException) as error:speech.recognize(b'audio')
    assert error.value.status_code==422 and not speech.lock.locked()

def test_auth_and_busy_do_not_accept_recording(speech,monkeypatch):
    monkeypatch.setenv('TRANSCRIPTION_TOKEN','test-token')
    with TestClient(speech.app) as client:
        assert client.post('/transcribe',content=b'audio').status_code==401
        speech.lock.acquire()
        try:assert client.post('/transcribe',content=b'audio',headers={'Authorization':'Bearer test-token'}).status_code==429
        finally:speech.lock.release()
        assert client.post('/transcribe',content=b'',headers={'Authorization':'Bearer test-token'}).status_code==422
        assert not speech.lock.locked()
