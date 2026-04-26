# CLI Path Generation

## Purpose

This document defines how `autocli` should derive `command.cli_path`.

`command.cli_path` is the compiler-generated default user-facing command shape for Typer registration.

It is not the same thing as `command.id`.

## Relationship To `command.id`

`command.id` and `command.cli_path` serve different purposes and should stay separate.

`command.id` is:

- technical
- stable
- collision-resistant
- derived from canonical endpoint identity

`command.cli_path` is:

- user-facing
- human-friendly
- allowed to be heuristic
- compiler-generated first and editable before validation

This separation means `cli_path` does not need to carry full identity semantics.

It only needs to produce a good default command tree for operators.

## Why This Needs Its Own Rule

The runtime CLI maps `cli_path` directly into Typer subcommands.

That means poor `cli_path` generation will leak into:

- help output
- discoverability
- command ergonomics
- naming collisions inside the generated CLI tree

The compiler therefore needs a deterministic `cli_path` rule, but it should optimize for readability rather than for technical uniqueness.

## Inputs

`cli_path` should be derived from normalized request metadata only.

The main inputs are:

- canonical HTTP method
- canonical host
- canonical `path_template`
- canonical `path_shape`

`cli_path` should not depend on:

- query values
- request body values
- response body values
- inferred schema shapes
- fixture-specific examples

The transport identity remains path-first.

The user-facing path should remain path-first too.

## Reference Points In `mitmproxy2swagger`

`mitmproxy2swagger` contains one naming idea worth reusing conceptually and several behaviors that should not be imported directly.

Useful reference points:

- `path_template_to_endpoint_name()` in `/Users/alexisboix/Projects/mitmproxy2swagger/mitmproxy2swagger/swagger_util.py`
- `path_to_regex()` and the `x-path-templates` workflow in `/Users/alexisboix/Projects/mitmproxy2swagger/mitmproxy2swagger/mitmproxy2swagger.py`
- generated summaries in `/Users/alexisboix/Projects/mitmproxy2swagger/example_outputs/lisek-out.swagger.yml`

## What To Borrow From `mitmproxy2swagger`

The most useful idea in `path_template_to_endpoint_name()` is its leaf-first naming instinct.

That function effectively says:

- ignore path parameters while choosing the human-facing name
- look at the tail of the path first
- treat a trailing action word differently from a plain resource segment

That instinct is good for `autocli`.

Examples where that instinct helps:

- `/basket/add` naturally becomes `basket add`
- `/coupons/activate/{promocode}` naturally wants `coupons activate`

The function in `swagger_util.py` is therefore a good conceptual reference for:

- using the path tail as the starting point for naming
- recognizing action-like leaf segments
- keeping parameter placeholders out of the base human-facing name

## What Not To Borrow

`autocli` should not reuse the upstream naming output directly.

The generated OpenAPI summaries in `mitmproxy2swagger` are useful evidence here:

- `/basket/add` -> `POST basket add` is reasonable
- `/inventory/{id}/full` -> `GET full by id` is too vague for a CLI command
- `/users/active` -> `POST active` drops the resource context and is too weak for help output

Those examples show why `autocli` should not adopt the upstream summary string as `cli_path`.

Specifically, `autocli` should not borrow:

- the HTTP method prefix in the final user-facing command path
- English summary phrases like `by id` as the command path itself
- names that discard the parent resource too aggressively
- the `x-path-templates` and `ignore:` editing workflow
- regex-driven path parameter guessing as the main source of endpoint identity

The `mitmproxy2swagger` parameter suggestion flow is a good example of what not to import into `autocli` architecture:

- `--param-regex` in `/Users/alexisboix/Projects/mitmproxy2swagger/mitmproxy2swagger/mitmproxy2swagger.py`
- suggested `ignore:` path templates in the same file
- greedy `x-path-templates` precedence in the same file

Those ideas fit OpenAPI curation.

They do not fit `autocli`'s direct command-module compiler.

## Goals

The generated `cli_path` should be:

- short
- readable
- deterministic
- reasonably stable for the same endpoint shape
- derived from the endpoint path rather than from incidental payload data

It should also be:

- good enough for first-pass help output
- easy for a human to edit later
- free of opaque suffixes when avoidable

## Output Shape

`command.cli_path` should remain a list of path segments.

Each segment should be:

- lowercase
- normalized to kebab-case
- safe for CLI usage

Examples:

- `setAddress` -> `set-address`
- `estimated_delivery_date` -> `estimated-delivery-date`
- `order-tips` -> `order-tips`

## Recommended Derivation Algorithm

### Step 1: Start From `path_template`

Generate the candidate from the canonical `path_template`, not from raw URLs.

The algorithm should operate on already normalized endpoint identity.

### Step 2: Split Into Path Segments

Split the canonical path into segments and ignore empty leading or trailing separators.

### Step 3: Remove Parameter Segments

Drop parameter placeholders such as `{p1}` or `{id}` from the user-facing path candidate.

Parameters still matter for:

- `command.id`
- request metadata
- argument mapping
- summary text

But they should usually not appear directly in `cli_path`.

`cli_path` should name the command, not spell out its parameter grammar.

### Step 4: Normalize Literal Segment Text

Normalize literal segments into CLI-friendly tokens.

Recommended normalization:

- lowercase the token
- split obvious camelCase boundaries when practical
- convert underscores and spaces to hyphens
- collapse repeated separators
- keep short numbers when they are part of a meaningful literal token

This should improve readability without changing the underlying endpoint identity.

### Step 5: Remove Leading Boilerplate Prefixes

Drop leading path segments that are structural namespace noise rather than useful command words.

Examples of segments that often fall into this category:

- `api`
- `rest`
- version prefixes such as `v2`, `v3`, or similar

Site-local namespace prefixes may also be omitted when they are clearly low-information.

Example:

- `/epood/cart/change` should prefer `cart change` rather than `epood cart change`

This omission should be conservative.

A segment should be treated as removable namespace noise only when it is:

- leading
- clearly structural rather than task-bearing
- not the only meaningful remaining literal segment

The original literal segment must still remain preserved in `path_template` and `path_shape`.

Only the user-facing `cli_path` becomes shorter.

### Step 6: Detect Action-Like Leaves

If the last remaining literal segment is action-like, prefer a `resource action` command shape.

Examples:

- `/cart/change` -> `cart change`
- `/basket/add` -> `basket add`
- `/coupons/activate/{p1}` -> `coupons activate`

This is the main idea worth borrowing from `mitmproxy2swagger`'s naming heuristic.

The exact action vocabulary does not need to be identical to the upstream `VERBS` list.

`autocli` can use a broader or more practical action lexicon as long as it stays deterministic.

Reasonable action-like examples include:

- `add`
- `attach`
- `activate`
- `change`
- `checkout`
- `create`
- `delete`
- `detach`
- `login`
- `logout`
- `remove`
- `search`
- `set`
- `submit`
- `update`
- `validate`

This list is a heuristic aid, not a claim of full semantic understanding.

### Step 7: Preserve Resource Context For Non-Action Leaves

If the last remaining literal segment is not action-like, keep enough parent resource context for the command to still be understandable.

Examples:

- `/inventory/{p1}/full` should prefer `inventory full`
- `/users/active` should prefer `users active`
- `/transactionSettings` should prefer `transaction-settings`

The important rule is:

- do not drop the resource context so aggressively that the command collapses into a vague word like `full` or `active`

### Step 8: Prefer Short Paths

The default `cli_path` should usually contain one or two segments.

Longer paths are allowed when necessary, but the compiler should prefer concise command trees.

In practice:

- singleton or obvious collection commands often need one segment
- resource-plus-action commands often need two segments
- resource-plus-subresource commands may occasionally need two or three segments

## Method Use Policy

HTTP method should not be the primary naming source for `cli_path`.

The method is transport metadata first, not CLI wording first.

However, method may be used secondarily for disambiguation when path-only naming collides.

## Collision Handling

Two different commands may legitimately derive the same initial `cli_path`.

Examples:

- `GET /products`
- `POST /products`
- `GET /products/{p1}`

All three could collapse toward `products` if no disambiguation rule exists.

The compiler should therefore resolve collisions deterministically without immediately falling back to opaque numbering.

Recommended resolution order:

1. derive the shortest human-friendly candidate from the path
2. if there is no collision, keep it
3. if there is a collision, apply REST-style method-and-shape disambiguation
4. if there is still a collision, expand by one more meaningful parent literal segment when available
5. if there is still a collision, stop and require manual `cli_path` editing rather than inventing an opaque suffix

The compiler should not silently append numeric endings such as:

- `products-2`
- `products-3`

Those names are technically easy but operator-hostile.

## REST-Style Disambiguation

When collisions happen on common REST shapes, use the method and path shape to produce a more helpful default.

Recommended defaults:

- `GET /products` -> `products`
- `GET /products` when colliding with another `products` command -> `products list`
- `GET /products/{p1}` -> `products get`
- `POST /products` -> `products create`
- `PUT /products/{p1}` -> `products update`
- `PATCH /products/{p1}` -> `products update`
- `DELETE /products/{p1}` -> `products delete`

This rule should be used mainly for collision handling and common REST resource/detail shapes.

It should not override a clear explicit action leaf such as `change`, `activate`, or `checkout`.

For example:

- `POST /cart/change` should stay `cart change`, not `cart create`

## Unresolved Cases

Some endpoints will still not produce a good automatic name.

Examples include:

- unusual RPC-like paths that slipped through filtering
- detail endpoints with weak literals and uncommon method usage
- multiple unrelated endpoints that still collapse after the normal disambiguation rules

In those cases, the correct behavior is not to fake confidence.

Instead:

- generate the best candidate available
- surface the ambiguity clearly
- require human adjustment of `command.cli_path` before validation

This is acceptable because `cli_path` is explicitly editable.

## Examples

Recommended defaults:

- `PUT /epood/cart/change` -> `["cart", "change"]`
- `POST /basket/add` -> `["basket", "add"]`
- `GET /inventory/{p1}/full` -> `["inventory", "full"]`
- `POST /users/active` -> `["users", "active"]`
- `GET /products` -> `["products"]`
- `POST /products` -> `["products", "create"]` when needed for disambiguation
- `GET /products/{p1}` -> `["products", "get"]`
- `DELETE /products/{p1}` -> `["products", "delete"]`

Anti-examples:

- `["get", "products"]`
- `["full"]`
- `["active"]`
- `["products-2"]`
- `["by-id"]`

## Interaction With `summary`

`cli_path` should stay short.

Longer human explanation belongs in:

- `command.summary`
- `command.description`
- argument help text

For example, parameter detail that does not belong in `cli_path` can still appear in summary text:

- `cli_path`: `["inventory", "full"]`
- summary: `Get full inventory details by item id`

## Non-Goals

`cli_path` generation is not trying to:

- infer full business meaning from payloads
- replace human review
- solve endpoint identity
- solve processor authoring
- import OpenAPI naming conventions wholesale

It is only trying to create a strong first-pass user-facing command path.

## Implementation Guidance

When this is implemented in code, the logic should stay:

- plain-function oriented
- deterministic
- path-first
- easy to unit test

The implementation should reference nearby behavior in `mitmproxy2swagger` only as a comparison aid.

It should not copy upstream architecture into `autocli`.
