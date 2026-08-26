# Operators

QLSM keeps a directory of named operators (SteamID64) so you don't have to
remember or retype IDs when granting server access. Operators are added and
removed in **Settings → Operators**, then assigned as Owner or Admin directly
from the Owner & Admins panel (its own tab on the instance Edit Config
modal; shown above the file manager on the Add Instance form and preset
Add/Edit pages).

## Add An Operator

1. Go to **Settings → Operators**.
2. Click **Add Operator**.
3. Enter a display name, the operator's SteamID64, and an optional default
   admin level (0-5, used to pre-fill the level when you assign them as an
   admin).
4. Submit.

## Delete An Operator

1. Go to **Settings → Operators**.
2. Find the operator and click **Delete**.

Deleting an operator only removes them from the directory — it does not
remove any `qlx_owner` or `access.txt` entry that already references their
SteamID64 on an instance or preset.

## Assign Owner Or Admin

The **Owner & Admins** panel appears wherever `server.cfg` / `access.txt`
are edited — its own tab on the instance Edit Config modal, and above the
file manager on the Add Instance form and the preset Add/Edit pages.

- **Owner** — pick an operator from the dropdown. This writes their
  SteamID64 into the `qlx_owner` line of `server.cfg`.
- **Admins** — pick an operator, choose a level (0-5), and click **Add**.
  This appends a `steamid|level` line to `access.txt`. Click the **×** next
  to an entry to remove it.

Typing a SteamID directly into `access.txt` in the editor also offers
autocomplete suggestions from the operator directory.

## Related Pages

- [Edit Configs, Plugins, Factories, And Hooks](../operations/edit-configs.md)
- [User Management & API Keys](user-management.md)
