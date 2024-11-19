bl_info = {
    "name": "Mixamo Fix Import",
    "blender": (4, 2, 0),
    "category": "Object",
}

import bpy
import os

class MixamoFixImportPanel(bpy.types.Panel):
    bl_label = "Mixamo Fix Import"
    bl_idname = "VIEW3D_PT_mixamo_fix_import"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Mixamo Fix'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        layout.prop(scene, "mixamo_import_folder")
        layout.prop(scene, "target_string")
        layout.operator("import.mixamo_fbx", text="Import Mixamo FBX")

def normalize_object(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

def rename_bones(target_string):
    # 获取当前场景中的所有对象
    objects = bpy.context.scene.objects
    for obj in objects:
        if obj.type != 'ARMATURE':
            continue
        for bone in obj.data.bones:
            if target_string in bone.name:
                new_name = bone.name.replace(target_string, "")
                bone.name = new_name

class ImportMixamoFBX(bpy.types.Operator):
    bl_idname = "import.mixamo_fbx"
    bl_label = "Import Mixamo FBX"
    
    def execute(self, context):
        folder = context.scene.mixamo_import_folder
        target_string = context.scene.target_string
        if not folder:
            self.report({'WARNING'}, "No folder specified")
            return {'CANCELLED'}
        
        fbx_files = [f for f in os.listdir(folder) if f.endswith('.fbx')]
        
        imported_objects = []
        for fbx_file in fbx_files:
            fbx_path = os.path.join(folder, fbx_file)
            bpy.ops.import_scene.fbx(filepath=fbx_path, ignore_leaf_bones=True, automatic_bone_orientation=True)
            
            for obj in bpy.context.selected_objects:
                imported_objects.append(obj)
                if obj.type == 'ARMATURE':
                    animations = [action for action in bpy.data.actions if action.name.startswith(obj.name)]
                    normalize_object(obj)
                    for child in obj.children:
                        if child.type == 'MESH':
                            normalize_object(child)
                    for action in animations:
                        action.name = fbx_file.split('.')[0]
        
        for obj in imported_objects:
            if obj.type == 'ARMATURE':
                for bone in obj.pose.bones:
                    if "hips" in bone.name.lower():
                        for fcurve in obj.animation_data.action.fcurves:
                            if fcurve.data_path.endswith('location'):
                                for keyframe in fcurve.keyframe_points:
                                    keyframe.co[1] *= 0.01

        # 调用重命名骨骼的函数
        rename_bones(target_string)

        # 获取当前场景中的所有对象
        objects = bpy.context.scene.objects
        
        # 过滤出需要排除的对象
        excluded_objects = [obj for obj in objects if not ("." in obj.name and obj.name.split(".")[-1].isdigit())]

        # 过滤出符合 `xxxx.xxx` 命名规则的对象，排除需要保留的对象
        objects_to_delete = [obj for obj in objects if ("." in obj.name and obj.name.split(".")[-1].isdigit() and obj not in excluded_objects)]

        # 先记录所有需要删除的对象
        delete_list = []
        for obj in objects_to_delete:
            delete_list.append(obj)
        
        # 删除记录的对象
        for obj in delete_list:
            bpy.data.objects.remove(obj, do_unlink=True)
        
        print("删除了所有符合命名规则 xxxx.xxx 的对象。")
        return {'FINISHED'}

def register():
    bpy.utils.register_class(MixamoFixImportPanel)
    bpy.utils.register_class(ImportMixamoFBX)
    bpy.types.Scene.mixamo_import_folder = bpy.props.StringProperty(
        name="FBX Folder",
        description="Folder path to import FBX files from",
        subtype='DIR_PATH'
    )
    bpy.types.Scene.target_string = bpy.props.StringProperty(
        name="Target String",
        description="String to be removed from bone names",
        default=""
    )

def unregister():
    bpy.utils.unregister_class(MixamoFixImportPanel)
    bpy.utils.unregister_class(ImportMixamoFBX)
    del bpy.types.Scene.mixamo_import_folder
    del bpy.types.Scene.target_string

if __name__ == "__main__":
    register()