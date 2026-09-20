# Language conventions

These conventions distinguish plugin instructions, machine identifiers, user
content, and project documentation. Classify the content by its role rather
than by whether an agent reads it or a schema validates it.

## Plugin instructions and machine identifiers

Write skill instructions, task prompts, and supporting execution guidance in
English. This includes `SKILL.md` bodies and the references supplied as
instructions to stage executors or reviewers.

Keep machine identifiers in their defined form. JSON keys, enum values, CLI
options, paths, and requirement or testpoint identifiers must match the
contracts and references that use them. Translating surrounding prose does
not rename those identifiers.

## User content and source material

Dialogue and generated explanatory prose follow the user's language. Examples
include design descriptions, review explanations, and notes inside structured
artifacts. Preserve quoted source wording in its original language, including
requirements copied into a ledger.

Schema validation governs the structure and allowed values of a field. It does
not make every string an English identifier. A ledger entry can therefore
contain English keys and a stage name alongside Chinese source text and notes:

```json
{
  "id": "REQ-RESET",
  "verbatim": "复位期间，输出必须为零。",
  "judge": "simulation",
  "note": "检查复位期间的输出行为。"
}
```

Here, `id` and `judge` are referenced identifiers. `verbatim` preserves the
source statement, and `note` contains an explanation in the user's language.
The schema can validate all four fields without changing their language roles.

A script that processes user text may contain patterns in that language.
Those patterns are input data for the matcher. Keep their exact spelling when
it affects matching, and keep the script's own execution guidance in English.

## Project documentation

User and contributor documentation follows its intended audience. An agent
reading a document does not, by itself, turn that document into an English-only
runtime instruction.

For committed English/Chinese pairs such as `ARCHITECTURE.md` and
`ARCHITECTURE.zh.md`, maintain the English source and its Chinese translation
in the same change. Keep their behavior descriptions, paths, commands, and
examples aligned. The English document is the maintained source, while the
translation should read naturally in Chinese.

When a file mixes instructions, identifiers, source quotations, and explanatory
prose, apply the convention to each part. Preserve both the machine contract
and the meaning of the user's material.
