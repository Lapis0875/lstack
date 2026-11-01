# CONTRACT

Conventions (from the boilerplates, do not restate per endpoint):
- Base path `/api`, Bearer JWT on everything except `/api/auth/*`.
- Errors: RFC 9457 `application/problem+json` `{type,title,status,detail,instance}`; validation 400 adds `errors[{field,message}]`.
- DTO names end in `Request` / `Response`; FE types are generated from `/v3/api-docs`, so names here are binding.
- Existing: `POST /api/auth/signup`, `POST /api/auth/login`, `GET /api/me`, `User{id,email,passwordHash}`.

## Entities (new)
| Entity | Fields |
| --- | --- |
| `Todo` | `id: Long`, `ownerId: Long (User)`, `title: String (1–200)`, `done: boolean`, `createdAt: Instant` |

## Endpoints (new)

### GET /api/todos
- 200 → `TodoResponse[]` = `[{ id, title, done, createdAt }]` (own items only)

### POST /api/todos
- Request `CreateTodoRequest { title: string }`
- 201 → `TodoResponse`
- 400 validation

### PATCH /api/todos/{id}
- Request `UpdateTodoRequest { title?: string; done?: boolean }`
- 200 → `TodoResponse`
- 404 not found / not owner

(delete rows above and add your own; keep the shape)
