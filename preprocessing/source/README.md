# preprocessing/source

원본 PDF를 도메인 이름으로 여기에 둔다 (저작물이라 PDF 자체는 gitignored):

```
preprocessing/source/korean_history.pdf
preprocessing/source/statistics.pdf
```

파이프라인 실행:

```
python -m preprocessing.pipeline_v2 --pdf preprocessing/source/<domain>.pdf
```

출력은 `preprocessing/result/<domain>_vN/`. 이후 `preprocessing/normalize.py`가
`input/<domain>/`(corpus.txt, captions.md, pagesplit.txt, images/)로 정규화한다.

이 폴더는 큐레이션 쇼케이스 도메인(국사·통계)의 dev-time 소스 전용이다.
프론트 실사용 업로드는 orchestrator(`/upload` -> `var/jobs/<id>`)가 따로 처리한다.
