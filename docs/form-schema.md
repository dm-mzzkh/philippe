# `form.yaml` reference

* file structure
   * top-level object: metadata + ordered list of `fields`
   * keys
      * name - form id (used to address the form / target table)
      * title - human-readable name shown to the user
      * table - (optional) DB table this form writes a row into
      * fields - ordered list; bot asks them top to bottom
   * the review (on_submit) is implicit, always runs last — you don't list it

* common field keys (every field accepts)
   * key - (required) answer id, usually the DB column name
   * type - (required) one of the field types below
   * label - (required) question text shown in chat
   * required - if true, can't be skipped (default true)
   * default - pre-selected / suggested value (meaning per type)
   * help - extra hint text under the question

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
      * options - list of choices (the buttons)
      * default - option pre-selected
      * allow_custom - if true, user may type a value not in options

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

   * repeat - a recurrence rule, asked in two steps
      * 1) period — buttons
         * Every day
         * Once a week (def)
         * Once a month
      * 2) frequency — buttons
         * 1 (def)
         * 2
         * 3
         * 4
         * or type any integer from 1 to 365
      * stored value combines period + frequency (e.g. "every 2 weeks")

   * photo / media / audio - attachments (user sends the message)
      * photo - a photo
      * media - a document / file
      * audio - an audio message

* on_submit — the review step (not declared as a field, runs automatically last)
   * shows everything entered
      * parameter: value
         * value is a link — tap it to jump back to that single field, change it, return to review
      * buttons
         * Cancel — discard the form
         * Submit & fill again — commit the record, then restart the same form for the next entry
   * note: in the MVP "submit" assembles the record; persisting to DB (INSERT/UPDATE) is on the roadmap
