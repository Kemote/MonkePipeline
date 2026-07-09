# Studio Asset DB — web app & API

## Run

```bash
pip install -r requirements.txt      # flask + sqlalchemy
python3 -m database.seed             # optional: sample data (only fills an empty DB)
python3 web_app/app.py               # http://127.0.0.1:5000
```

The SQLite file (`database/studio.db`) and the preview images
(`database/preview_img/`) live inside the `database` folder and are
created automatically on first start.

## Data model

* **assets** — one record per asset *version*: `id`, `name`, `author`,
  `version`, `status` (`stable` / `wip` / `canceled`), `preview_img`
  (file name in `database/preview_img`), `created_date` (set automatically).
  Only one version of an asset (records sharing a `name`) can be `stable` —
  marking a record stable demotes the previous stable one to `wip`.
* **steps** — the asset's steps dict, one row per entry:
  `key` (str) → `value` (int), plus per-entry `status`, `modified_date`
  and `modified_by`.

## API

| Method | URL | Description |
|---|---|---|
| GET | `/api/assets` | list / search assets |
| GET | `/api/assets/<id>` | single asset |
| POST | `/api/assets` | create |
| PUT / PATCH | `/api/assets/<id>` | modify |
| DELETE | `/api/assets/<id>` | delete |

### Searching

```bash
# filter by any field: id, name, author, version, status
curl "127.0.0.1:5000/api/assets?name=monkey_hero"

# only return some fields
curl "127.0.0.1:5000/api/assets?name=monkey_hero&fields=id,version,status"

# status_stable flag: return the version of that asset marked "stable",
# no matter which version was matched
curl "127.0.0.1:5000/api/assets/3?status_stable=1"
```

### Creating / modifying

JSON body — steps accept a plain int, a detail dict, or `null` (remove on modify);
an image can be embedded as base64:

```bash
curl -X POST 127.0.0.1:5000/api/assets -H "Content-Type: application/json" -d '{
  "name": "rock_set", "author": "tomek", "version": "v001", "status": "wip",
  "steps": {"model": 1, "lookdev": {"value": 2, "status": "stable"}},
  "modified_by": "tomek",
  "preview_img_b64": "<base64...>", "preview_img_name": "rock.png"
}'
```

Or multipart with a real file (steps as a JSON string):

```bash
curl -X POST 127.0.0.1:5000/api/assets \
  -F name=rock_set -F author=tomek -F version=v001 -F status=wip \
  -F 'steps={"model": 1}' -F preview_img=@rock.png
```

Uploaded images are stored in `database/preview_img/` and served at
`/preview_img/<filename>`; asset payloads reference them in `preview_img`.
