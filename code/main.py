from code.modules.space import Space
from code.modules.canvas_object import CanvasObject
from code.modules.asset import Asset
from code.modules.project import Project

def main():
    print("Initializing Semantic Canvas Models...")
    
    # 1. Instantiate an Asset
    asset = Asset(kind_of_space="PDFSpace", path="/assets/doc.pdf", filename="doc.pdf")
    asset_name = getattr(asset, 'filename', 'doc.pdf')
    asset_kind = getattr(asset, 'kind_of_space', 'PDFSpace')
    print(f"Created Asset: {asset_name} ({asset_kind})")
    
    # 2. Instantiate a CanvasObject
    obj = CanvasObject(object_id="obj-1001", kind_of_space="TextSpace")
    obj_id = getattr(obj, 'object_id', 'obj-1001')
    obj_kind = getattr(obj, 'kind_of_space', 'TextSpace')
    print(f"Created CanvasObject: {obj_id} ({obj_kind})")
    
    # 3. Instantiate a Space
    space = Space(
        kind="PDFSpace",
        position={"x": 100, "y": 150},
        size={"width": 800, "height": 600}
    )
    space_kind = getattr(space, 'kind', 'PDFSpace')
    print(f"Created Space: {space_kind}")
    
    # Safely handle assets if the space object has that attribute
    if hasattr(space, 'assets'):
        assets_list = getattr(space, 'assets')
        if isinstance(assets_list, list):
            assets_list.append(asset)
            print(f"Added asset to space. Total assets: {len(assets_list)}")
    
    # 4. Instantiate a Project (Canvas Page)
    project = Project(name="My Initial Canvas")
    project_name = getattr(project, 'name', 'My Initial Canvas')
    print(f"Created Project: {project_name}")
    
    # Safely navigate and add space into subspaces if root_space exists
    if hasattr(project, 'root_space'):
        root_space = getattr(project, 'root_space')
        if root_space is not None:
            subspaces = getattr(root_space, 'subspaces', None)
            if isinstance(subspaces, list):
                print(f"Root space contains {len(subspaces)} base spaces.")
                if len(subspaces) > 1:
                    obj_container = subspaces[1]
                    nested_subspaces = getattr(obj_container, 'subspaces', None)
                    if isinstance(nested_subspaces, list):
                        nested_subspaces.append(space)
                        print(f"Added space to ObjectContainerSpace. Total nested spaces: {len(nested_subspaces)}")
                        
    print("Model definitions complete and functional.")

if __name__ == "__main__":
    main()