from py3dtiles.tileset import TileSet

class Kit3DTileset(TileSet):

    # tileset 생성 재정의
    def to_dict(self):
        git_tileset = super().to_dict()

        git_tileset["asset"]["version"] = "1.0"
        git_tileset["asset"]["STW"] = True
        git_tileset["asset"]["extras"] = {
            "author": "BHB",
        }

        return git_tileset
