# starvector

## License

Starvector is free software. You can use it, change it, and share it with the
terms of the GNU Affero General Public License, version 3 (AGPL-3.0). The full
text is in [LICENSE](LICENSE).

The AGPL-3.0 applies to network use too. If you operate a changed version of
Starvector as a website, you must give its users the source code of your version.

The [NOTICE](NOTICE) file adds one term with section 7(b) of the license. Each
copy or changed version must keep a credit to the author. One location where the
public can find it is sufficient, for example a README or an About page.

To use Starvector with different terms, for example in closed-source software,
contact the author about a commercial license.

## Open source software

Starvector uses the open source software, open datasets, open models, and
public services in the tables that follow. Each name goes to the home of the
project. The license is the one that the project declares, as an SPDX
identifier where there is one.

The version of each project is in `pyproject.toml`, `uv.lock`,
`web/package.json`, and `web/pnpm-lock.yaml`, and the two lock files also hold
the dependencies of the named projects.

### Server

| Name | Role in Starvector | License |
|---|---|---|
| [Python](https://www.python.org) | Language of the scoring engine and the server | `PSF-2.0` |
| [FastAPI](https://fastapi.tiangolo.com/) | HTTP API of the trial server | `MIT` |
| [Starlette](https://starlette.dev/) | Web toolkit below FastAPI | `BSD-3-Clause` |
| [Pydantic](https://docs.pydantic.dev) | Data validation in FastAPI | `MIT` |
| [Uvicorn](https://uvicorn.dev/) | Server process | `BSD-3-Clause` |
| [HTTPX](https://www.python-httpx.org) | HTTP client for the model providers and the downloads | `BSD-3-Clause` |
| [NumPy](https://numpy.org) | Array mathematics of the scoring pipeline | `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` |
| [Pillow](https://python-pillow.github.io) | Image decode and image output | `MIT-CMU` |
| [PyArrow](https://arrow.apache.org/) | Reads the Parquet files of the image corpus | `Apache-2.0` |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Downloads the dataset files | `Apache-2.0` |
| [argon2-cffi](https://argon2-cffi.readthedocs.io/) | Password digests | `MIT` |
| [ALTCHA for Python](https://github.com/altcha-org/altcha-lib-py) | Proof of work at sign-up | `MIT` |
| [SQLite](https://www.sqlite.org) | Results index and public results database | Public domain |

The local models are optional. They use these projects:

| Name | Role in Starvector | License |
|---|---|---|
| [PyTorch](https://pytorch.org) | Tensor engine of the local models | `Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT` |
| [torchvision](https://github.com/pytorch/vision) | Image functions for the local models | `BSD-3-Clause` |
| [Transformers](https://github.com/huggingface/transformers) | Loads the SigLIP 2 checkpoints | `Apache-2.0` |
| [controlnet-aux](https://github.com/huggingface/controlnet_aux) | Interface to the line-art detector | `Apache-2.0` |
| [Triton](https://triton-lang.org/) | Part of the PyTorch set for Intel graphics processors | `MIT` |

### Web app

| Name | Role in Starvector | License |
|---|---|---|
| [React](https://react.dev/) | Interface library | `MIT` |
| [TanStack Query](https://tanstack.com/query) | Server data in the browser | `MIT` |
| [TanStack Router](https://tanstack.com/router) | Paths of the app | `MIT` |
| [ALTCHA widget](https://altcha.org) | Proof of work at sign-up | `MIT` |
| [Phosphor Icons](https://phosphoricons.com) | Icons | `MIT` |
| [Red Hat Display, Red Hat Text, and Red Hat Mono](https://github.com/RedHatOfficial/RedHatFont) | Typefaces of the interface, from the [Fontsource](https://fontsource.org) packages | `OFL-1.1` |
| [Newsreader](https://github.com/productiontype/Newsreader) | Italic typeface, from the Fontsource packages | `OFL-1.1` |

### Tools

| Name | Role in Starvector | License |
|---|---|---|
| [uv](https://docs.astral.sh/uv) | Python environment and lock file | `Apache-2.0 OR MIT` |
| [pytest](https://docs.pytest.org/) | Python tests | `MIT` |
| [Vale](https://vale.sh) | Prose lint | `MIT` |
| [Git](https://git-scm.com) | Version control | `GPL-2.0-only` |
| [Node.js](https://nodejs.org) | Runtime of the web tools | `MIT` |
| [pnpm](https://pnpm.io) | Package manager of the web app | `MIT` |
| [Vite](https://vite.dev) | Development server and build of the web app | `MIT` |
| [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react) | React in the Vite build | `MIT` |
| [vite-plugin-pwa](https://github.com/vite-pwa/vite-plugin-pwa) and [Workbox](https://github.com/GoogleChrome/workbox) | Installable web app with an offline cache | `MIT` |
| [TypeScript](https://www.typescriptlang.org/) | Type checks of the web code | `Apache-2.0` |
| [DefinitelyTyped](https://github.com/DefinitelyTyped/DefinitelyTyped) | Type definitions for Node.js and React | `MIT` |
| [Biome](https://biomejs.dev) | Lint and format of the web code | `MIT OR Apache-2.0` |
| [Vitest](https://vitest.dev) | Unit tests of the web code | `MIT` |
| [Testing Library](https://testing-library.com) | Component tests | `MIT` |
| [jsdom](https://github.com/jsdom/jsdom) | Browser environment for the unit tests | `MIT` |
| [Playwright](https://playwright.dev) | End-to-end tests in a browser | `Apache-2.0` |
| [resvg-js](https://github.com/thx/resvg-js) | Makes the PNG icons from SVG files | `MPL-2.0` |

### Deployment

| Name | Role in Starvector | License |
|---|---|---|
| [Ubuntu Server](https://ubuntu.com/server) | Operating system of the box | One license for each package: see the [license table](https://ubuntu.com/legal/open-source-licences) |
| [Caddy](https://caddyserver.com) | HTTPS edge and proxy in front of the server | `Apache-2.0` |
| [systemd](https://systemd.io) | Units and timers of the server | `LGPL-2.1-or-later` |
| [restic](https://restic.net) | Backup of the store | `BSD-2-Clause` |
| [ufw](https://launchpad.net/ufw) | Firewall | GNU GPL version 3 |
| [unattended-upgrades](https://github.com/mvo5/unattended-upgrades) | Automatic system updates | `GPL-2.0-or-later` |
| [OpenSSH](https://www.openssh.com) | Operator sign-in and tunnel | BSD licenses |
| [rsync](https://rsync.samba.org) | Copies the pool data to the box | GNU GPL version 3 |

### Data, models, and public services

| Name | Role in Starvector | License |
|---|---|---|
| [WIT](https://github.com/google-research-datasets/wit) ([paper](https://arxiv.org/abs/2103.01913)), as [`wikimedia/wit_base`](https://huggingface.co/datasets/wikimedia/wit_base) | Source of the pool images | `CC-BY-SA-4.0` for `wikimedia/wit_base`, `CC-BY-SA-3.0` for the Google release |
| [Wikimedia Commons](https://commons.wikimedia.org) | Home of each pool image. Each reveal credits the file page | Each file has its own free license, or is in the public domain |
| [FS-COCO](https://github.com/pinakinathc/fscoco) ([paper](https://arxiv.org/abs/2203.02113)) | Sketch and photograph pairs for the validation | `CC-BY-NC-4.0` |
| [COCO](https://cocodataset.org/) ([paper](https://arxiv.org/abs/1405.0312)) | Photographs of the FS-COCO pairs | See the project |
| [Informative Drawings](https://github.com/carolineec/informative-drawings) ([paper](https://arxiv.org/abs/2203.12691)) | Line-art model for the line drawing of each pool image. The weights come from [`lllyasviel/Annotators`](https://huggingface.co/lllyasviel/Annotators) | `MIT` for the project. The weights copy declares `other`: see the project |
| [SigLIP 2](https://github.com/google-research/big_vision/blob/main/big_vision/configs/proj/image_text/README_siglip2.md) ([paper](https://arxiv.org/abs/2502.14786)) | Optional local text encoder and image encoder | `Apache-2.0` |
| [SecLists](https://github.com/danielmiessler/SecLists) | Source of the table of usual passwords that sign-up refuses | `MIT` |
| [drand](https://drand.love) | Public randomness beacon of the League of Entropy. Its pulse picks each target after the close | `Apache-2.0 OR MIT` for the software |

The references for these datasets, models, and public services:

```text
WIT
    K. Srinivasan, K. Raman, J. Chen, M. Bendersky, and M. Najork.
    "WIT: Wikipedia-based Image Text Dataset for Multimodal Multilingual
    Machine Learning." SIGIR 2021. https://arxiv.org/abs/2103.01913

FS-COCO
    P. N. Chowdhury, A. Sain, A. K. Bhunia, T. Xiang, Y. Gryaditskaya, and
    Y.-Z. Song. "FS-COCO: Towards Understanding of Freehand Sketches of
    Common Objects in Context." ECCV 2022. https://arxiv.org/abs/2203.02113

COCO
    T.-Y. Lin, M. Maire, S. Belongie, L. Bourdev, R. Girshick, J. Hays,
    P. Perona, D. Ramanan, C. L. Zitnick, and P. Dollár. "Microsoft COCO:
    Common Objects in Context." 2014. https://arxiv.org/abs/1405.0312

Informative Drawings
    C. Chan, F. Durand, and P. Isola. "Learning to Generate Line Drawings
    that Convey Geometry and Semantics." CVPR 2022.
    https://arxiv.org/abs/2203.12691

SigLIP 2
    M. Tschannen, A. Gritsenko, X. Wang, M. F. Naeem, I. Alabdulmohsin,
    N. Parthasarathy, T. Evans, L. Beyer, Y. Xia, B. Mustafa, O. Hénaff,
    J. Harmsen, A. Steiner, and X. Zhai. "SigLIP 2: Multilingual
    Vision-Language Encoders with Improved Semantic Understanding,
    Localization, and Dense Features." 2025. https://arxiv.org/abs/2502.14786

SecLists
    D. Miessler, J. Haddix, I. Portal, and g0tmi1k. The SecLists project.
    https://github.com/danielmiessler/SecLists

drand
    The drand project and the League of Entropy. "Drand - A Distributed
    Randomness Beacon Daemon." https://github.com/drand/drand
```

The pool preparation also uses hosted services that are not open source:
OpenRouter, Google Gemini models, OpenAI models, and Voyage embeddings.
