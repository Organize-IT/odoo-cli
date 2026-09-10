# Errors

Every failure is an `OdooError` carrying `.code`, `.message` and `.data`. The
class decides the CLI exit code.

| Exception | Exit | Raised when |
|---|---|---|
| `OdooError` | 1 | Odoo returned an error we do not classify further |
| `OdooAccessError` | 1 | authenticated but not allowed (ACL, record rule) |
| `OdooValidationError` | 1 | a business rule rejected the call |
| `OdooMissingError` | 1 | the record does not exist or is not visible |
| `OdooUsageError` | 2 | bad arguments, unknown field, unknown alias |
| `OdooConnectionError` | 3 | network, HTTP status, bad URL, rate limit exhausted |
| `OdooAuthError` | 3 | credentials rejected |
| `OdooRefusedError` | 4 | a guard refused; Odoo was never called |

Odoo's own exception name is mapped on the way in, so `odoo.exceptions.UserError`
and `odoo.exceptions.ValidationError` both become `OdooValidationError`, and
`MissingError` becomes `OdooMissingError`.

The server traceback is dropped from error output unless `--verbose` is passed;
it is always available on `.data["debug"]` in the library.

::: odoocli.errors
