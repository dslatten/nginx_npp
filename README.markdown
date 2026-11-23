# Nginx syntax highlighting for Notepad++

User-defined languages (UDLs) for editing Nginx configuration files in Notepad++. The light and dark versions share their keywords and parsing rules, with separate colors.

## Install

1. Download the XML for your editor background:
   - [userDefineLang_nginx.xml](https://raw.githubusercontent.com/dslatten/nginx_npp/master/userDefineLang_nginx.xml): light colors, named `Nginx`.
   - [userDefineLang_nginx_dark.xml](https://raw.githubusercontent.com/dslatten/nginx_npp/master/userDefineLang_nginx_dark.xml): dark colors, named `Nginx-Dark`.
2. In Notepad++, open **Language > User Defined Language > Define your language...**.
3. Click **Import...** and select the downloaded XML file.
4. Close the dialog and restart Notepad++.
5. Open your configuration file and select **Language > Nginx** or **Language > Nginx-Dark**.

Both definitions associate with `.conf` files. If another language also uses that extension, or you import both versions, select the intended language manually. Select `Nginx-Dark` when using a dark editor background; changing Notepad++'s theme does not select a different UDL for you. Files without a `.conf` extension can also use either language through the Language menu.

### Update an existing installation

Download the new XML first. In the UDL dialog, select the existing `Nginx` or `Nginx-Dark` definition. Use **Export...** if you want to keep custom colors or keywords, then **Remove** that definition before importing its replacement. Repeat for the other version if installed, and restart Notepad++.

If you installed XML files directly in Notepad++'s `userDefineLangs` directory, close Notepad++ and replace those files instead. Use one installation method for each language name to avoid duplicate definitions. The [Notepad++ UDL manual](https://npp-user-manual.org/docs/user-defined-language-system/) explains the configuration-file locations.

## Coverage

The keyword source targets **Nginx 1.31.9** and its bundled open source modules, including optional modules. It retains every keyword from this project's original light and dark definitions, and legacy directives identified in the official 0.8.55 and 1.8.1 sources, including SPDY. Future vocabulary updates preserve older directive names automatically. Highlighting does not establish that a directive is available in a particular Nginx build or valid in its current context.

Coverage includes HTTP/2, HTTP/3 and QUIC, gRPC, stream configurations, modern TLS directives, and newer JSON and CONNECT-tunnel directives. This is not a complete vocabulary for Nginx Plus, njs, OpenResty, or third-party modules.

The UDL handles comments, quoted strings, variables, named locations, and brace folding. Quoted strings use one consistent style, including any variables inside them. Outside strings, `$name` receives variable styling and `${name}` is protected from brace folding.

UDL highlighting does not validate directive contexts. A `#` embedded in an unquoted argument, such as a URL fragment, can look like a comment; quote that argument for reliable highlighting. Variable styling can also extend across adjacent path text in the same token. See the [visual fixture and review notes](examples/README.md) for cases to check in Notepad++.

## Maintain the definitions

The generated XML files are committed so users can install them without Python. To change the definitions, use **Python 3.9 or newer**. The tools use only the Python standard library.

- [`src/keywords.json`](src/keywords.json) contains the shared vocabulary.
- [`src/lexer.json`](src/lexer.json) contains the shared parsing and folding rules.
- [`src/themes.json`](src/themes.json) contains the light and dark styles.
- [`src/sources.json`](src/sources.json) records vocabulary provenance and the source version.

The `src/Words*.txt` files are generated, readable keyword references.

Run these commands from the repository root after editing the source files:

```sh
python tools/generate.py
python tools/generate.py --check
python -m unittest discover -s tests -v
```

`--check` verifies that the committed output matches the generator without rewriting it. Make vocabulary and style changes in `src`, then regenerate both XML files together.

To refresh keywords for a new Nginx release, download and extract its source archive from the [official downloads page](https://nginx.org/en/download.html). Point the updater at the extracted source directory and supply that release's version:

```sh
python tools/update_keywords.py --source-dir PATH --version VERSION
python tools/generate.py
python tools/generate.py --check
```

Replace `PATH` with the extracted Nginx source directory, quoting it if it contains spaces, and replace `VERSION` with its version number. Review the changes to the vocabulary, provenance, and generated files before committing. The updater reads source files; it does not build or run Nginx.

To add coverage from another historical release, append `--legacy-source OLD_VERSION OLD_PATH` to the updater command. The option can be repeated. Historical sources enrich the compatibility list without replacing the current release's vocabulary. Provenance is recorded in `src/sources.json`.

### Validate a change

Run the generation check and unit tests, then import both generated XML files into a current Notepad++ installation. Open [`examples/highlighting.conf`](examples/highlighting.conf) and [`examples/lexical-edge-cases.conf`](examples/lexical-edge-cases.conf), and follow the [visual review checklist](examples/README.md). Record the Notepad++ version and results when submitting a change. These fixtures are for highlighting review and are not intended to pass `nginx -t`.

On November 22, 2026, both themes were loaded and visually checked in **Notepad++ 8.9.9.1 on Windows** using isolated settings directories. Checks covered modern directives, case sensitivity, empty strings, escaped quotes and backslashes, quoted comment markers, `$name` and `${name}`, named and predicate locations, and block folding. The light check used LF line endings; the dark check used a CRLF copy without a final newline. The GitHub Actions workflow checks generated files and runs the unit tests.

## AI assistance

The November 2026 refresh was developed with AI assistance from OpenAI Codex using GPT-6 Astra. The changes were checked with automated tests and visual checks in Notepad++ 8.9.9.1, as described above.

## Contributions

The 2024 keyword updates proposed by [jazini110 in PR #6](https://github.com/dslatten/nginx_npp/pull/6) and [PR #7](https://github.com/dslatten/nginx_npp/pull/7), and [stpettersens' HTTP/2 proposal in PR #8](https://github.com/dslatten/nginx_npp/pull/8), helped identify the need for this refresh. Earlier contributions, including duzun's dark theme and string handling, remain recorded in the repository history.

For directive behavior and supported contexts, consult the [Nginx documentation](https://nginx.org/en/docs/). For UDL customization, use the [Notepad++ UDL manual](https://npp-user-manual.org/docs/user-defined-language-system/).
