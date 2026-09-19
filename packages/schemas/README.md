# @plancheck/schemas

The JSON files are the API between engines. These TypeScript types are the
written-down version of that contract.

The authoritative definitions live in two places and **must be edited
together**:

| Contract        | TypeScript                | Python                          |
| --------------- | ------------------------- | ------------------------------- |
| `building.json` | `src/building.ts`         | `apps/api/app/models/building.py` |
| sheet classification | `src/sheets.ts`      | `apps/api/app/models/sheets.py` |
| project / API   | `src/project.ts`          | `apps/api/app/models/project.py` |

There is no codegen step yet. It isn't worth the setup cost until the schema
stops moving, which per the build order is after E1 runs on pages 8 and 33-37.

Field names, types and nullability must match exactly. If you change one side,
change the other in the same commit.
