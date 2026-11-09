# Runtime verification

This release pins the BabelDOC commit installed by the image build and records the versions that a process actually imported. It does not make unlocked dependencies byte-for-byte reproducible.

## Expected BabelDOC commit

`021d0e7f3e4974efdd5e7f46feadbb5aafba130e` is the image install on `impl/r1-2026-11-06`, package version `0.6.4.103`. That commit keeps the BabelDOC lock on PyMuPDF 1.x. An incomplete paragraph is marked and the PDF is still written. The image install uses this full SHA, and the Dockerfile requires `pymupdf>=1.26.7,<2`.

Do not build with the previous command that omits `BABELDOC_REF`. Compose rejects an unset or empty value. The Dockerfile rejects any value that is not 40 lowercase hex characters, including `main`, a short SHA, a non-hex string, and an uppercase SHA.

## Release unit

The parent Compose file is not in the consumer git repo. Its bytes are the release unit:

`/Users/yun/Nextcloud/Project/PDFMathTranslate-next/docker-compose.yml`

SHA-256: `2381bc95bdd81584855d06f904ad932bb4c99d26a57d9da35e920764b558251a`

`services.pdfmt-next.build.args.BABELDOC_REF` is `${BABELDOC_REF:?BABELDOC_REF must be a full commit SHA}`. `context` remains `./PDFMathTranslate-next`. `dockerfile` remains `Dockerfile`. The Dockerfile argument name is `BABELDOC_REF`.

## Image build

```
BABELDOC_REF=<40位小写SHA> docker compose -f /Users/yun/Nextcloud/Project/PDFMathTranslate-next/docker-compose.yml build pdfmt-next
```

The release command uses `BABELDOC_REF=021d0e7f3e4974efdd5e7f46feadbb5aafba130e`.

## Mounted DeepLX script

The image pin above does not include DeepLX. Compose mounts `./config` at `/root/.config/pdf2zh`. On 2026-11-09 the live `deeplx.py` and `deeplx_v3.2.1-production-final.py` were replaced in place and the service was restarted. Both files are SHA-256 `172063fa62487a2c35a88ddd47f12d47306e7d300c042daea79ea2ea7434b990`. The configured script is `deeplx_v3.2.1-production-final.py`. BabelDOC stays `0.6.4.103` at `021d0e7f3e4974efdd5e7f46feadbb5aafba130e`. The consumer image stays `afa7cdb77799450b23c9aa4f69fe5ffd89886f36`, version `2.9.0`. Cache files and glossaries were not deleted. The inner cache key includes this script hash, so the next translation misses old rows.

Before building, confirm `BABELDOC_REF` is this full SHA. The Dockerfile accepts any 40 lowercase hex characters, so an older full SHA such as `98c63369382c72a738c289b702ebd46b956569a2` still passes the check and skips the PyMuPDF 1.x pin.

## Read-only check

Compose mounts do not prove which tree was imported. After a future authorized deploy, and only when reading the running container is authorized, write a manifest. Do not rebuild or restart the container in order to read it.

```
python -m pdf2zh_next.runtime_manifest --out /tmp/runtime-manifest.json --deeplx-script PATH
```

Compare BabelDOC path, version, and git revision; consumer path, version, and git revision; and the DeepLX sha256. A null git revision means that directory is not a repository or `git rev-parse HEAD` failed. Do not store `main` or `latest` in its place.

A passing manifest on a development machine is not a deployment. Compare it with the running container after the image is recreated.
