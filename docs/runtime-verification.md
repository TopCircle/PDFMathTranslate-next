# Runtime verification

This release pins the BabelDOC commit installed by the image build and records the versions that a process actually imported. It does not make unlocked dependencies byte-for-byte reproducible.

## Expected BabelDOC commit

`98c63369382c72a738c289b702ebd46b956569a2` is the local `impl/r1-2026-11-06` head. That commit is local and not pushed. A real image build is not part of this task and cannot fetch that SHA until a later authorized push. The container is not deployed.

Do not build with the previous command that omits `BABELDOC_REF`. Compose rejects an unset or empty value. The Dockerfile rejects any value that is not 40 lowercase hex characters, including `main`, a short SHA, a non-hex string, and an uppercase SHA.

## Release unit

The parent Compose file is not in the consumer git repo. Its bytes are the release unit:

`/Users/yun/Nextcloud/Project/PDFMathTranslate-next/docker-compose.yml`

SHA-256: `2381bc95bdd81584855d06f904ad932bb4c99d26a57d9da35e920764b558251a`

`services.pdfmt-next.build.args.BABELDOC_REF` is `${BABELDOC_REF:?BABELDOC_REF must be a full commit SHA}`. `context` remains `./PDFMathTranslate-next`. `dockerfile` remains `Dockerfile`. The Dockerfile argument name is `BABELDOC_REF`.

## Later build

Run this only after that BabelDOC commit is pushed and a build is separately authorized. Do not run it for this task. Do not rebuild or restart a container from this document.

```
BABELDOC_REF=<40位小写SHA> docker compose -f /Users/yun/Nextcloud/Project/PDFMathTranslate-next/docker-compose.yml build pdfmt-next
```

After the local head is pushed, the same command uses `BABELDOC_REF=98c63369382c72a738c289b702ebd46b956569a2`.

## Read-only check

Compose mounts do not prove which tree was imported. After a future authorized deploy, and only when reading the running container is authorized, write a manifest. Do not rebuild or restart the container in order to read it.

```
python -m pdf2zh_next.runtime_manifest --out /tmp/runtime-manifest.json --deeplx-script PATH
```

Compare BabelDOC path, version, and git revision; consumer path, version, and git revision; and the DeepLX sha256. A null git revision means that directory is not a repository or `git rev-parse HEAD` failed. Do not store `main` or `latest` in its place.

A passing manifest on a development machine is not a deployment. Deploy and restart stay a later, separate operation.
