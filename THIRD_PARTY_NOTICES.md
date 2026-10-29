# Third-party notices

birdROMs is released under the [MIT License](LICENSE). It builds on the open-source software below.
Dependencies are installed from their package registries at build time (`backend/uv.lock`,
`frontend/yarn.lock` list the exact versions) and are not copied into this repository, except for the
fonts bundled into the web UI.

## Licenses of the dependencies

An audit of the locked dependency sets found only permissive or weak-copyleft licenses, and no GPL or AGPL:

| Where | Licenses |
| --- | --- |
| Backend (Python) | BSD-3-Clause (Django, Django REST Framework, Authlib, django-storages, whitenoise, ...), MIT (gunicorn, redis, ...), Apache-2.0 (requests, boto3, cryptography, ...), MIT-CMU/HPND (Pillow) |
| Frontend (JavaScript) | MIT (the large majority), ISC, BSD-2/3-Clause, Apache-2.0, BlueOak-1.0.0, OFL-1.1 (the fonts below) |

Items worth knowing about:

- **psycopg2-binary** is LGPL (with exceptions). It is used unmodified as a normal
  Python dependency (dynamically linked), which the LGPL allows. Replace it with the `psycopg2` source
  package or `psycopg` if you need a fully permissive stack.
- **certifi** (CA bundle) is MPL-2.0 and **lightningcss** (a build-time CSS tool pulled in by the front-end
  toolchain) is MPL-2.0. Both are unmodified.
- **caniuse-lite** (browser data used at build time) is CC-BY-4.0.
- The Docker images additionally contain Debian (python:3.12-slim), Alpine (nginx and Node base
  images), nginx (BSD-2-Clause), PostgreSQL and Redis images (only when you run the compose file) under
  their own licenses.

## Fonts bundled in the web UI

Both fonts come from the [Fontsource](https://fontsource.org/) packages and are licensed under the
SIL Open Font License 1.1 (full text below).

- **Chakra Petch**: Copyright 2018 The Chakra Petch Project Authors (https://github.com/m4rc1e/Chakra-Petch.git)
- **Press Start 2P**: Copyright 2012 The Press Start 2P Project Authors (cody@zone38.net), with Reserved Font Name "Press Start 2P"

```text
-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

The same notice is served by a running instance at `/third-party-notices.txt`.
