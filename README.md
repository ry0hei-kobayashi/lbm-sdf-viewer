# LBM Model Viewer

TRI の [lbm_eval](https://github.com/ToyotaResearchInstitute/lbm_eval) が配布している
`lbm_eval_models` 1.1.0 の全モデル (SDF / URDF / ステーション構成の dmd.yaml、計157ファイル) を
ブラウザで見るためのビューアです。Drake の ModelVisualizer と Meshcat を使っています。

## 使い方

```bash
docker compose up
```

初回はイメージをビルドします。`lbm_eval_models` の wheel (約820MB) を GitHub Release から
ダウンロードするため、数分かかります。イメージは約3.2GBです。

起動したらブラウザで <http://localhost:8080> を開きます。

- 左の一覧からモデルを選ぶと、右側の 3D 表示が切り替わります (切り替えに数秒かかります)。
- 検索欄で名前を絞り込めます (例: `station`, `flir`, `mug`)。
- 「座標軸を表示」で各リンクの座標軸が出ます。
- 3D 表示の右上 Controls で、関節のスライダー操作と、衝突形状の表示
  (Scene > drake > proximity) ができます。
- Controls の「Stop Running」を押すと 3D 表示が止まります。一覧からモデルを選び直せば再開します。

止めるときは `Ctrl-C`、または `docker compose down` です。

## ポートを変える

8080 (一覧ページ) と 7000 (Meshcat) を使います。ほかで使用中の場合は環境変数で変えられます。

```bash
WEB_PORT=8081 MESHCAT_PORT=7001 docker compose up
```

別の PC から見る場合は、両方のポートに届く必要があります。SSH 経由なら次のように転送します。

```bash
ssh -N -L 8080:localhost:8080 -L 7000:localhost:7000 <ホスト>
```

## 主なモデル

| ファイル | 内容 |
| --- | --- |
| `stations/cabot/add_cabot_simulation.dmd.yaml` | cabot ステーション全体 (起動時に表示) |
| `stations/riverway/add_riverway_finray_mimic.dmd.yaml` | riverway ステーション全体 |
| `stations/franka_station/station_arm_cart_gantry.sdf` | アームを載せるカートとガントリ |
| `stations/franka_station/station_gantry_base_plate.sdf` | ガントリのベースプレート |
| `stations/franka_station/station_natural_brown_table_top_compliant.sdf` | テーブル天板 |
| `robots/schunk_grippers/flir_assembly_primitives.sdf` | 手先の FLIR カメラとレンズの組立 |
| `stations/cameras/framos_d415e_keepout.sdf` | シーンカメラ D415e |

157ファイルのうち14は、親の構成から読み込まれる前提の部分ファイル
(`add_table_top_weld.dmd.yaml` など) で、単体では表示できません。選ぶとエラーが表示されます。

## 構成

| ファイル | 役割 |
| --- | --- |
| `Dockerfile` | Drake と `lbm_eval_models` を入れたイメージ |
| `docker-compose.yml` | ポート割り当てと起動設定 |
| `app.py` | 一覧ページの配信、API、モデルごとの Meshcat プロセスの起動と切り替え |
| `static/index.html`, `static/style.css`, `static/app.js` | 一覧ページ |

コンテナ内で確認用のコマンドも使えます。

```bash
docker compose run --rm viewer python3 app.py list    # モデル一覧
docker compose run --rm viewer python3 app.py check   # 全モデルの読み込み確認
```
