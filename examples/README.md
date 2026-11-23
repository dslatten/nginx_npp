# Visual highlighting fixtures

Open [`highlighting.conf`](highlighting.conf) in Notepad++ to review the generated UDLs. This visual fixture combines Nginx, Nginx Plus, njs, and OpenResty directives with placeholder paths and upstreams. Use it to review highlighting in the editor.

[`lexical-edge-cases.conf`](lexical-edge-cases.conf) is a compact companion for checking quotes, escapes, variables, comments, case sensitivity, and folding together. Its capitalized `Server` is deliberately invalid and should use the default text style.

Import the two XML files from the repository root, then select **Language > Nginx** with a light editor background and **Language > Nginx-Dark** with a dark background. Review the same file in each language. Syntax behavior should match; colors should differ.

## Review checklist

- Modern directives such as `http2`, `http3`, `grpc_pass`, `ssl_certificate_cache`, `json_set`, `tunnel_pass`, and `ssl_preread` receive directive styling.
- `js_import` (njs), `auth_jwt` (Nginx Plus), `more_set_headers` (Headers More), and `content_by_lua_file` (OpenResty Lua) receive the same directive styling.
- `http`, `events`, `server`, `location`, and `stream` receive structural styling.
- `$host`, `${host}`, `$request_id`, and variables in the predicate location receive variable styling outside quotes. Quoted strings keep one uniform style, including variables inside them.
- `@fallback` receives named-location styling in both its declaration and its use.
- Single-quoted and double-quoted strings end at the intended quote. Escaped quotes and backslashes do not leave the following lines styled as a string.
- A `#` inside a quoted string stays inside that string. The comment after the `/lexing` response starts at the unquoted `#` and ends at the newline.
- Braces in strings, regex repetition counts, and `${host}` do not create extra folds. Actual context blocks, including nested locations, fold at their matching braces.
- Closing a folded block does not hide the next sibling block or change its highlighting.

These are review expectations, not a record of a completed Notepad++ test. A useful validation note identifies the Notepad++ version, the language tested, and any failing line or screenshot. UDL rules do not validate directive contexts, module availability, or parameter values. Quote arguments containing `#` to avoid comment styling; variable styling may extend into adjacent path text within the same token.

## Feature references

- [HTTP/2](https://nginx.org/en/docs/http/ngx_http_v2_module.html) and [HTTP/3](https://nginx.org/en/docs/http/ngx_http_v3_module.html)
- [JSON extraction](https://nginx.org/en/docs/http/ngx_http_json_module.html) and [predicate locations](https://nginx.org/en/docs/http/ngx_http_core_module.html#location)
- [CONNECT tunneling](https://nginx.org/en/docs/http/ngx_http_tunnel_module.html)
- [Stream TLS preread](https://nginx.org/en/docs/stream/ngx_stream_ssl_preread_module.html)
