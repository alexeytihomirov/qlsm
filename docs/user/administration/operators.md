# Operators

QLSM keeps a directory of named operators — the people who run or moderate
your servers, each with their SteamID64. Add someone once, then assign them as
a server's **Owner** or **Admin** by picking their name, instead of looking up
and retyping their SteamID in `server.cfg` and `access.txt`.

Operators are managed in **Settings → Operators** and assigned from the
**Owner & Admins** tab wherever server configs are edited.

![Operators page](../images/operators-page.png)

## Add An Operator

1. Go to **Settings → Operators**.
2. Click **Add Operator**.
3. Enter a display name and the operator's SteamID64 (17 digits, starting
   with `7656119`).
4. Choose a **Default admin level** (0-5). This is the level filled in when
   you pick the operator to add as an Admin in the Owner & Admins tab.
5. Click **Add Operator**.

![Add Operator dialog](../images/operators-add-modal.png)

Each SteamID64 can only be in the directory once.

## Delete An Operator

1. Go to **Settings → Operators**.
2. Click the delete icon on the operator's row and confirm.

Deleting an operator only removes them from the directory. It does **not**
remove them from any server: an existing `qlx_owner` line with their
SteamID64 stays in place, and so does their in-game permission. To take someone's access away, remove them in the Owner &
Admins tab and save.

## Assign Owner Or Admin

In the instance **Edit Config** window and the **Add Instance** form, the
**Owner & Admins** controls have their own tab, to the right of **Hooks**. On
the preset add and edit pages they appear as a panel above the config fields.

![Owner & Admins panel](../images/owner-admins-panel.png)

- **Owner** — pick an operator. This writes their SteamID64 to the
  `qlx_owner` line of `server.cfg`. The owner always has level 5. The change
  takes effect when the server restarts, so leave **Restart after saving** on.
- **Admins** — pick an operator, choose a level from **1 to 5**, and click
  **Add**. Admins are picked from the operator directory above, so granting a
  raw SteamID means adding that person there first.

Higher levels unlock more minqlx admin commands. Level **5** is the highest
and includes `!setperm`, which lets that admin grant permissions to other
players, so only give 5 to people you trust with that.

The admin list lives only on the game server, in minqlx's own Redis
permission database. The tab shows exactly what the server has right now,
including anyone promoted in-game with `!setperm`. QLSM keeps no copy of
its own.

The **Manage operators** link opens **Settings → Operators** in a new tab.

QLSM reads the admin list from the server as soon as **Edit Configuration**
opens, so the tab is already filled when you switch to it. **Save Preset**
includes the admin list even if you never opened the tab.

An admin whose SteamID is not in the operator directory shows as a bare
SteamID with an **Add to operators** button. It opens the same Add Operator
dialog as the Operators page, on top of the configuration window, with the
SteamID and current level already filled in. Enter a name and click **Add
Operator**; the row then shows that name. Your unsaved configuration edits
are not affected.

## What Happens When You Save

**Save Configuration** writes only what you changed in the tab. Admins you
didn't touch, including anyone promoted in-game while the window was open,
are left alone. Nothing is re-applied on later saves, restarts or deploys, so
a change made in-game with `!setperm` stays and shows up the next time you
open the tab.

- **Adding** an admin gives them that level in-game.
- **Removing** an admin sets their in-game level to 0.
- Changes apply without a server restart, though minqlx's permission cache
  can take up to about 30 seconds to pick them up.

There is no inline level editor: to change someone's level, remove them and
add them back at the new level.

Instances that share a Redis database also share in-game admins: an admin
added on one instance is an admin on the other.

### Presets

A preset stores the admin list in an `admins.json` file. **Save Preset**
takes the list the server currently has (plus your unsaved edits), even if you
never opened the tab. A new instance created from the preset gets those admins
once, when it's deployed. Loading a preset into an existing instance replaces
the tab's list; save to apply the difference.

### If The Server Can't Be Read

If QLSM can't reach the server (for example, SSH or Redis is down), the tab
shows a banner and the admin list can't be edited. **Save Preset** still
saves, but without admins, and tells you so. If a save can't write your admin
changes, the config is still saved and the instance log shows a warning.

## access.txt

`access.txt` is Quake Live's own file — it only holds Quake Live's native
`admin`, `mod` and `ban` role lines. It no longer holds QLSM admin levels:
those live in minqlx's Redis permissions on the server, not on disk.
Any numeric `steamid|level` line left over from an older QLSM version is
stripped out automatically the next time the file is saved, whether from an
instance or a preset.

## Related Pages

- [Edit Configs, Plugins, Factories, And Hooks](../operations/edit-configs.md)
- [User Management & API Keys](user-management.md)
