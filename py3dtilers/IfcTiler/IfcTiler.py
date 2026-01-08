import logging
from datetime import datetime
import time
from pathlib import Path
from ..Common import Tiler, Groups
from .ifcObjectGeom import IfcObjectsGeom


from ..Kit3d.db_writer_ifc import IFCDBWriter

class IfcTiler(Tiler):

    def __init__(self):
        super().__init__()
        self.supported_extensions = ['.ifc', '.IFC']

        self.parser.add_argument('--grouped_by',
                                 nargs='?',
                                 default='IfcTypeObject',
                                 choices=['IfcTypeObject', 'IfcGroup', 'IfcSpace'],
                                 help='Either IfcTypeObject or IfcGroup (default: %(default)s)'
                                 )
        
        self.parser.add_argument('--with_BTH',
                                 dest='with_BTH',
                                 action='store_true',
                                 help='Adds a Batch Table Hierarchy when defined')
        
        self.parser.add_argument("--db",
            dest="db_config",
            default="dbname=ifc user=postgres password=admin host=localhost port=5432",
            help="PostgreSQL DSN for IFC DB , TEST Config"
        )

    def get_output_dir(self):
        """
        Return the directory name for the tileset.
        """
        if self.args.output_dir is None:
            return "tileset"
        else:
            return self.args.output_dir
        
    #오버라이드
    def parse_command_line(self):
        super().parse_command_line()

        base_out = Path(self.args.output_dir or "tileset")
        first = Path(self.args.paths[0]) # input 파라미터

        if first.exists() and first.is_dir():
            input_name = first.name # 단일파일
        else:
            input_name = first.stem # 디렉터리명
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_dir = base_out / f"{ts}_{input_name}_3dtiles"

        self.args.output_dir = str(new_dir)

    
    def get_file_logger(self,logs_dir: Path) -> logging.Handler:
        logs_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = logs_dir / f"{ts}_{len(self.files)}_ifc.log"

      
        handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        return handler
    
    def get_valid_ifc_file(self):
        valid_files = []
        for f in self.files:
            p = Path(f)
            if not p.exists():
                logging.error(f"[SKIP] Not found: {p}")
                continue
            if not p.is_file():
                logging.error(f"[SKIP] Not a file: {p}")
                continue
            valid_files.append(str(p))

        if not valid_files:
            raise FileNotFoundError("No valid IFC files found in input paths.")
        
        logging.info(f"Valid files: {len(valid_files)} / total: {len(self.files)}")
        
        return valid_files

    def from_ifc(self, grouped_by, with_BTH):
        objects = []
        logs_dir = Path("logs")
        root = logging.getLogger()

        handler = self.get_file_logger(logs_dir)
        root.addHandler(handler)

        ifc_files = self.get_valid_ifc_file()

        db = IFCDBWriter(self.args.db_config, write_geom=True) 
        
        try:
            for ifc_file in ifc_files:
                run_id = db.create_run(ifc_file)
                try:
                    print("Reading " + str(ifc_file))
                    if grouped_by == 'IfcTypeObject':
                        pre_tileset = IfcObjectsGeom.retrievObjByType(ifc_file, with_BTH, db=db)
                    elif grouped_by == 'IfcGroup':
                        pre_tileset = IfcObjectsGeom.retrievObjByGroup(ifc_file, with_BTH)
                    elif grouped_by == 'IfcSpace':
                        pre_tileset = IfcObjectsGeom.retrievObjBySpace(ifc_file, with_BTH)

                    objects.extend([objs for objs in pre_tileset.values() if len(objs) > 0])
                except Exception as e:
                    logging.exception(f"Failed processing {ifc_file}: {e}")
            
            groups = Groups(objects).get_groups_as_list()
            return self.create_tileset_from_groups(groups, "batch_table_hierarchy" if with_BTH else None)
        finally:
            root.removeHandler(handler)
            handler.close()
            db.close()
    
def main():
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.NullHandler()],
        force=True
    )

    start_time = time.time()
    logging.info('Started')
    ifc_tiler = IfcTiler()
    ifc_tiler.parse_command_line()
    args = ifc_tiler.args

    tileset = ifc_tiler.from_ifc(args.grouped_by, args.with_BTH)

    if tileset is not None:
        tileset.write_as_json(Path(ifc_tiler.get_output_dir(), 'tileset.json'))
    logging.info("--- %s seconds ---" % (time.time() - start_time))

if __name__ == '__main__':
    main()
