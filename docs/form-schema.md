# `form.yaml` reference

* file structure
   * top-level object: metadata + ordered list of `fields`
   * keys
      * name - form id (used to address the form / target table)
      * title - human-readable name shown to the user
      * kind - (optional) `form` (default, data entry) or `query` (read view, below)
      * table - (optional) DB table this form writes a row into
      * query - (query forms only) the SQL to run; must return a `label` column
      * context - (optional) columns filled from the message, not asked (see below)
      * fields - ordered list; bot asks them top to bottom (data-entry forms)
   * the review (on_submit) is implicit, always runs last — you don't list it

* kind: query — a VIEW, not a data-entry form
   * picked from /forms like any form; runs `query` and lists the rows
   * the SQL must return a `label` column — that text becomes each row
   * needs a database; empty result → "all done" message
   * WITHOUT `action`: read-only plain text list (no buttons)
   * WITH `action`: each row is a button; tapping it launches another form,
     pre-filled from that row (so the view becomes actionable)
      * action.form - the form to launch on tap (must be a loaded form)
      * action.prefill - `{target_field_key: row_column}`; the launched form
        starts with those fields set and asks only the rest
      * the `query` must also return any columns named in `prefill`
   * example: `examples/today.yaml` lists tasks due today/overdue; tapping one
     opens `log` with its `task` pre-filled, so you just confirm date / comment

* common field keys (every field accepts)
   * key - (required) answer id, usually the DB column name
   * type - (required) one of the field types below
   * label - (required) question text shown in chat
   * required - if true, can't be skipped (default true)
   * default - pre-selected / suggested value (meaning per type)
   * help - extra hint text under the question
   * column - (optional) DB column to write to; defaults to `key`. Use it when the
     column name differs from the answer key (e.g. select `task` → `task_id`)
   * tags - (optional, attachment fields) list of Hydrus tags to apply to
     each uploaded file. If an entry matches a field `key`, its resolved value
     is substituted (e.g. `tags: ["food", name]` tags the file with the literal
     "food" and the value of the `name` field).

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
      * Back on the FIRST field exits the form back to the /forms menu
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
      * options - one of three forms:
         * static list: `options: [todo, in_progress, done]`
         * structured DB source (loaded once per dialog):
            * table - table to read options from
            * value - column stored as the answer (e.g. `id`)
            * label - column shown on the button (e.g. `title`)
            * where - (optional) raw SQL filter, e.g. `active = true`
            * order_by - (optional) raw SQL ordering
         * raw query (any SQL — for DISTINCT, joins, aggregates):
            * `options: {query: SELECT DISTINCT user_name AS value, user_name AS label FROM logs ORDER BY 1}`
            * must return columns named `label` and `value`, OR a single column
              (used for both); mutually exclusive with table/value/label/where/order_by
      * default - option pre-selected (a value)
      * allow_custom - if true, user may type a value not in options
      * with a DB source the button shows the `label` but the row stores the
        `value` — pair it with `column:` to target the right column

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

   * time - a clock time, typed as HH:MM
      * accepts 23:30, 23.30, 2330, or 7:15
      * stored as a real time value (a TIME column)

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
      * photos - collect multiple photos in one field, tap "Готово" to finish
        * uploaded to Hydrus Network on submit; content hash stored in the column
        * the `tags` field key (above) lets you attach Hydrus tags to each upload
        * `show_images` action in query forms re-downloads from Hydrus by hash

* on_submit — the review step (not declared as a field, runs automatically last)
   * shows everything entered, one button per field
      * each button reads `<field label>: <short answer>` and is the edit link —
        tap it to jump back to that single field, change it, return to review
      * long answers are shortened to one line on the button
      * buttons
         * Cancel — discard the form
         * Submit & fill again — commit the record, then restart the same form for the next entry
   * on submit the record is written: a real INSERT when a database is configured
     (see docs/database.md), otherwise just logged

* how answers become a DB row (data-entry forms) — see docs/database.md
   * each field writes its `column` (default `key`); `repeat` writes `period`+`every`;
     a dynamic `select` stores the chosen value (id) into its `column`
   * `context` columns are added from the message; column types are cast
     automatically (so a str lands in an enum column)

* worked examples (in examples/)
   * task.yaml — data entry into `tasks` (title, repeat → period+every, bool)
   * log.yaml — into `logs`: dynamic select (task_id), date, optional text, context
   * today.yaml — `kind: query` actionable view (tap a due task → log it)
   * history.yaml — `kind: query` read view (recent completion log)
   * sleep.yaml / sleep-log.yaml — record a night's sleep (date + time fields) /
     view the sleep diary with computed hours (👍 if > 7h)
   * workout.yaml / workout-log.yaml — log a gym set (type or pick an exercise —
     free text suggested from past entries — sets × reps @ weight) / view the
     recent training diary
   * form.yaml — every field type at once (no table → logged only)
