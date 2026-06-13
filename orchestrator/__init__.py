"""회랑 오케스트레이션: 업로드 -> 비동기 인덱싱 -> 점진 서빙의 골격.

이 패키지는 serve.py(frozen RAG 데모)와 독립된 FastAPI 앱이다. 1차 빌드는
전처리/인덱싱/빌드를 전부 STUB(sleep + placeholder 산출물)로 두고, 잡 큐 ->
워커 -> 상태 전이 -> 부분 준비 플래그 골격이 끝까지 도는지만 증명한다.

serve.py, warm_query.py, palace/, configs, golden 은 건드리지 않는다.
"""
