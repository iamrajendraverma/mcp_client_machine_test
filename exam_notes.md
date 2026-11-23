# MCP Exam Notes: Tool Input Schema

## 1. What is an input schema?

An MCP tool's `inputSchema` describes the arguments that the tool accepts. It is based on JSON Schema.

The MCP client discovers this schema through `tools/list`. The model/client uses it to understand which arguments to provide when calling a tool. The MCP server should validate the arguments again before executing the tool.

## 2. Main components

| Keyword / component | Meaning | Example |
|---|---|---|
| `inputSchema` | MCP tool-definition field containing the JSON Schema for tool arguments | `"inputSchema": { ... }` |
| `type` | Data type of the value | `"object"`, `"string"`, `"integer"`, `"number"`, `"boolean"`, `"array"` |
| `properties` | Defines the named fields accepted by an object | `"city": { "type": "string" }` |
| `required` | Lists fields that must be supplied | `["city"]` |
| `title` | Human-readable title/label for a schema or field | `"City Name"` |
| `description` | Explains the purpose or expected value of a schema or field | `"Name of the city"` |
| `enum` | Restricts a value to a fixed set of choices | `["celsius", "fahrenheit"]` |
| `items` | Defines the schema for each element in an array | `{ "type": "string" }` |
| `default` | Annotates a suggested/default value | `3` |
| `additionalProperties` | Controls whether object fields not listed in `properties` are allowed | `false` |
| `minimum` / `maximum` | Sets numeric bounds | `1` / `10` |
| `minLength` / `maxLength` | Sets string-length bounds | `1` / `100` |

**Important corrections:**
- The correct spelling is `properties`, not “propertices”.
- `unit` is not a standard JSON Schema keyword. It is commonly just the name of an input property, such as a temperature unit. A custom vocabulary/extension may define additional keywords, but do not assume one exists.
- `hint` is not a standard JSON Schema keyword. Put usage guidance in a relevant `description` or tool instructions instead.
- `title` and `description` are descriptive annotations; they do not by themselves validate the value.
- `required` belongs to the containing object schema. It is an array of property names, not a boolean on each property.
- A `default` annotation does not guarantee that every validator or MCP server will automatically insert that value. Handle defaults explicitly when needed.

## 3. Example: weather tool input schema

This is the schema portion of an MCP tool definition:

```json
{
  "name": "get_weather",
  "description": "Get the weather forecast for a city.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "city": {
        "type": "string",
        "title": "City Name",
        "description": "Name of the city to check."
      },
      "unit": {
        "type": "string",
        "title": "Temperature Unit",
        "description": "Temperature measurement unit.",
        "enum": ["celsius", "fahrenheit"]
      },
      "days": {
        "type": "integer",
        "title": "Forecast Days",
        "description": "Number of forecast days.",
        "minimum": 1,
        "maximum": 7,
        "default": 3
      }
    },
    "required": ["city"],
    "additionalProperties": false
  }
}
```

### How to read this example

- The top-level `type: object` means the tool arguments must be a JSON object.
- `city` is mandatory because it appears in `required`.
- `unit` is optional; if supplied, it must be either `celsius` or `fahrenheit`.
- `days` is optional and, when supplied, must be an integer from 1 to 7.
- `additionalProperties: false` disallows undeclared fields.

A valid argument object could be:

```json
{
  "city": "Bhopal",
  "unit": "celsius",
  "days": 3
}
```

This is invalid because `city` is missing:

```json
{
  "unit": "celsius"
}
```

## 4. Common JSON Schema types

| Type | Example value |
|---|---|
| `string` | `"Bhopal"` |
| `integer` | `5` |
| `number` | `36.5` |
| `boolean` | `true` |
| `array` | `["lab", "billing"]` |
| `object` | `{"city": "Bhopal"}` |

Array example:

```json
{
  "type": "object",
  "properties": {
    "categories": {
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "required": ["categories"]
}
```

## 5. How the schema is used in the MCP flow

1. Client initializes the MCP connection and negotiates capabilities.
2. Client sends `tools/list` to discover available tools and their descriptions/input schemas.
3. The model/client selects a tool and prepares arguments that match its schema.
4. Client sends `tools/call` with the tool name and arguments.
5. Server validates the arguments and executes the tool if valid.
6. Server returns a tool result or an error.

**Security point:** Client-side validation improves usability, but it is not a security boundary. The server must validate inputs independently because a client can send malformed or malicious arguments.

## 6. Input schema vs output schema

| Input schema | Output schema |
|---|---|
| Describes arguments accepted by a tool | Describes the structure of the tool's result |
| Used when preparing a `tools/call` request | Used to describe/validate structured results |
| MCP tool field: `inputSchema` | Optional MCP tool field: `outputSchema` |

## 7. Quick exam revision

Remember:

- `type` = What kind of data?
- `properties` = Which fields are available?
- `required` = Which fields must be provided?
- `title` = What is the human-readable label?
- `description` = What does the field mean?
- `enum` = Which values are allowed?
- `items` = What type/shape does each array element have?
- `additionalProperties` = Are extra object fields allowed?
- `unit` = Usually a property name, not a standard JSON Schema keyword.
- `hint` = Not a standard JSON Schema keyword.

**One-line answer:** An MCP tool's `inputSchema` is a JSON Schema contract that describes the expected argument structure, data types, required fields, and constraints.
