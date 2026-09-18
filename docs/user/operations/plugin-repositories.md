# Repositories

**Settings → Repositories** lets you add third-party sources and install their contents: plugins go into QLSM's shared plugin folder, addons onto the addon packages volume.

A new QLSM install already lists one repository, **Doomsday's Plugins Repository** (`https://github.com/D00MSDAYDEVICE/minqlx`). None of its plugins are downloaded until you pick them. You can delete it; it won't come back when QLSM restarts or updates.

## Add A Repository

1. Click **Add Repository** and enter a name and the repository's URL.
2. QLSM fetches `<URL>/qlsm-repository.json` (or, when that's absent, the older plugins-only `<URL>/qlsm-plugins.json`) right away and lists the plugins and addons it describes.

**GitHub links work directly.** Paste the repository page URL, for example `https://github.com/D00MSDAYDEVICE/minqlx`, and QLSM converts it to the raw file address itself, looking on the `main` branch and then `master`. The card keeps showing the address you typed. To use another branch or a subfolder, paste that page's URL, such as `https://github.com/owner/repo/tree/dev/plugins`. Private repositories aren't supported.

Any other file host works too, as long as the files are served directly. The URL is treated as a folder that holds the manifest and the files it lists.

Names must be unique (ignoring case), and a URL can only be added once (ignoring a trailing `/`). Click the sync icon on a repository to fetch its list again.

A repository's `qlsm-repository.json` looks like this. Every field except `filename` (plugins) and `id`/`zip` (addons) is optional:

```json
{
  "plugins": [
    {
      "filename": "hello_qlsm.py",
      "label": "Hello QLSM",
      "description": "Replies to !hello.",
      "runtime": "minqlxtended",
      "requires_qlsm_version": "1.36.0",
      "sha256": "…hash of the LF-normalized .py…",
      "cvars": [
        { "cvar": "qlx_helloMessage", "label": "Reply text", "type": "string", "default": "Hello!", "description": "What !hello replies with." }
      ]
    },
    { "filename": "another_plugin.py" }
  ],
  "addons": [
    {
      "id": "my-addon",
      "version": "1.2.0",
      "zip": "my-addon.zip",
      "sha256": "…hash of the zip…",
      "label": "My Addon",
      "description": "What it does.",
      "requires_qlsm_version": "1.41.0"
    }
  ]
}
```

One file describes everything in the repository. A plugins-only repository can keep using the older filename `qlsm-plugins.json` with just the `plugins` array; the entries are the same.

`cvars` (and `commands`) use the same format as a `.ql-plugin.json` file. When you download a plugin, QLSM saves its label, description, cvars and commands next to it, which gives it an editable settings form (see [Plugin Settings](edit-configs.md#plugin-settings-cvars)).

A plugin can still ship its own `<name>.ql-plugin.json` file next to its `.py` file. If it does, QLSM uses that file instead of the plugin's entry in `qlsm-plugins.json`.

Inline `cvars`/`commands` need QLSM 1.36.0 or newer. Older versions ignore them.

**`sha256` powers the update badges.** For each listed plugin (hash of the `.py` with line endings normalized to LF) and addon (hash of the `.zip` as served), QLSM compares the declared hash/version against what's installed locally and shows **Update available** / **Up to date** / **Not installed** in the list. Entries without a `sha256` (or, for addons, without a `version`) simply show no status.

## Download Plugins

![A plugin repository expanded, showing its plugin list](../images/plugin-repositories.png)

1. Expand a repository and tick the plugins you want.
2. A plugin that doesn't declare its runtime needs one picked in its row before **Download selected** is enabled.
3. Click **Download selected**.

- Each plugin goes into the shared plugin folder for its runtime: `data/shared-plugins/minqlx/` or `data/shared-plugins/minqlxtended/` under your QLSM install. That folder is kept outside the QLSM image, so downloads survive updates and are visible to every part of QLSM. The plugins QLSM ships with stay untouched; a download with the same name as a built-in plugin replaces it on every host once you confirm the overwrite prompt.
- If a file with the same name is already there and its code differs, QLSM asks before overwriting it (a copy that only differs in line endings is left as is). Each file in that prompt has a checkbox and a **Diff** button. Untick any file you want to keep, and click **Diff** to compare this server's copy (left) with the repository's copy (right) first. Removed lines are red, added lines green, and unchanged sections are folded. Overwriting a plugin also replaces its `.ql-plugin.json` sidecar with the repository's, or removes it when the repository has none; the diff only compares the `.py` file.

![The overwrite prompt listing two existing plugins](../images/plugin-overwrite-prompt.png)

![The diff window comparing the server's copy of a plugin with the repository's](../images/plugin-diff.png)

- A plugin that needs a newer QLSM version than you're running shows a red warning. You can still download it.

## Use A Downloaded Plugin

Downloading a plugin also pushes QLSM's shared plugin folder to every **Active** host that runs the plugin's runtime. The success message names the hosts. A host that is busy with another job, or not Active, is listed as skipped; run [Check for Updates](check-for-updates.md) on it later, or use the push button described below.

1. Open the instance's config (or **Deploy A New Instance**) and go to the **Plugins** tab. The plugin is listed with the other shared plugins (see [Shared Plugins](edit-configs.md#shared-plugins)), marked **shared** once the host has it.
2. If the row shows **not on host** instead, the host has not received the file yet. Click the upload icon next to it to push the shared folder to that host, and wait for the badge to clear.
3. Tick the plugin and save. Restart the instance to load it.

## Install Addons

A repository that lists addons shows them in their own table under the plugin list, with an **Install** button per row (it reads **Update** when the repository has a newer version than the installed one).

Installing downloads the addon's `.zip` and puts it through exactly the same installer and checks as uploading it on the Addons page — including verifying the archive against the `sha256` the repository declares, when it declares one. Like an upload, **the addon is not live until QLSM restarts**; it shows as *pending restart* on the Addons page until then. Updating works the same way: installing over an existing addon replaces it atomically, and its settings are kept.
