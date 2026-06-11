# `form.yaml` reference

* file structure
   * top-level object: metadata + ordered list of `fields`
   * keys
      * name - form id (used to address the form / target table)
      * title - human-readable name shown to the user
      * table - (optional) DB table this form writes a row into
      * context - (optional) columns filled from the message, not asked (see below)
      * fields - ordered list; bot asks them top to bottom
   * the review (on_submit) is implicit, always runs last — you don't list it

* common field keys (every field accepts)
   * key - (required) answer id, usually the DB column name
   * type - (required) one of the field types below
   * label - (required) question text shown in chat
   * required - if true, can't be skipped (default true)
   * default - pre-selected / suggested value (meaning per type)
   * help - extra hint text under the question
   * column - (optional) DB column to write to; defaults to `key`. Use it when the
     column name differs from the answer key (e.g. select `task` → `task_id`)

* context (top-level, optional) — columns the bot fills from the message, not asked
   * a list of `{column, from}` entries
      * column - the DB column to write
      * from - the source value: `user_id`, `user_name`, or `chat_id`
   * example:
      * `context: [{column: user_id, from: user_id}, {column: user_name, from: user_name}]`

* universal behaviour (applies to every field, not repeated below)
   * Back button — always at the bottom
      * returns to previous field
      * already-collected answers are kept (back/forward never loses data)
   * review at the end — shown automatically after the last field
   * defaults — when a type has buttons + a default, the default option is marked (def) so one tap accepts it

* field types

   * title - short single-line text (a name / heading)
      * just type it
      * or send a voice message → bot transcribes into the field

   * text - long multi-line text (a description)
      * same as title: type it, or send a voice message

   * number - numeric value with range
      * min - lowest accepted value
      * max - highest accepted value
      * presets - optional numbers shown as quick-tap buttons
      * validates value is in [min, max], re-asks on bad input
      * with presets: buttons appear, but typing a custom value is still allowed (within range)

   * bool - yes/no
      * buttons
         * Yes
         * No

   * select - choose one from a fixed set
      * options - EITHER a static list of strings, OR a DB-loaded source:
         * static: `options: [todo, in_progress, done]`
         * dynamic source (loaded from the DB once per dialog):
            * table - table to read options from
            * value - column stored as the answer (e.g. `id`)
            * label - column shown on the button (e.g. `title`)
            * where - (optional) raw SQL filter, e.g. `active = true`
            * order_by - (optional) raw SQL ordering
      * default - option pre-selected (a value)
      * allow_custom - if true, user may type a value not in options
      * with a dynamic source the button shows the `label` but the row stores the
        `value` — pair it with `column:` to target the right FK column

   * date - a calendar date
      * quick buttons
         * Day before yesterday
         * Yesterday
         * Today (def)
         * Tomorrow
      * or type it
         * weekday of the current week — mon, tue, … (localized)
         * day and month — 01.01, 1.1, or 1 1
         * day, month and year — same separators, e.g. 01.01.2026

   * repeat - a recurrence rule, one message with two button rows
      * row 1) period
         * Every day
         * Once a week
         * Once a month
      * row 2) frequency
         * ×1
         * ×2
         * ×3
         * ×4
         * or type any integer from 1 to 365
      * tap one button from each row (in any order); the chosen button is marked
        "• " and the message is edited in place — nothing is re-sent
      * the field completes once both a period and a frequency are chosen
      * stored value combines period + frequency (e.g. "every 2 weeks")
      * writes TWO columns: `period` and `every` (override with `period_column` /
        `every_column`); it ignores the common `column:` key

   * photo / media / audio - attachments (user sends the message)
      * photo - a photo
      * media - a document / file
      * audio - an audio message

* on_submit — the review step (not declared as a field, runs automatically last)
   * shows everything entered, one button per field
      * each button reads `<field label>: <short answer>` and is the edit link —
        tap it to jump back to that single field, change it, return to review
      * long answers are shortened to one line on the button
      * buttons
         * Cancel — discard the form
         * Submit & fill again — commit the record, then restart the same form for the next entry
   * note: in the MVP "submit" assembles the record; persisting to DB (INSERT/UPDATE) is on the roadmap
