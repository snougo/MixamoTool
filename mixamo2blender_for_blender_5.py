bl_info = {
    "name": "Mixamo Fix Import (5.0 Naming Fix)",
    "blender": (5, 0, 0),
    "category": "Object",
    "author": "ChatGPT Fixed",
    "version": (1, 1, 3),
    "location": "3D Viewport > Sidebar > Mixamo Fix",
    "description": "Import Mixamo FBX with correct naming and Blender 5.0 support.",
}

import bpy
import os

class MixamoFixImportProperties(bpy.types.PropertyGroup):
    mixamo_import_folder: bpy.props.StringProperty(
        name="Mixamo FBX Folder",
        description="Folder path to import FBX files from",
        subtype='DIR_PATH'
    )
    bone_name_prefix_to_remove: bpy.props.StringProperty(
        name="Bone Name Prefix to Remove",
        description="String to be removed from bone names (e.g., 'mixamorig:')",
        default="mixamorig:"
    )

class MixamoFixImportPanel(bpy.types.Panel):
    bl_label = "Mixamo Fix Import"
    bl_idname = "VIEW3D_PT_mixamo_fix_import"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Mixamo Fix'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.mixamo_fix_import_properties
        
        layout.prop(props, "mixamo_import_folder")
        layout.prop(props, "bone_name_prefix_to_remove")
        layout.operator("import.mixamo_fbx", text="Import & Fix Mixamo FBX", icon='IMPORT')

# --- 核心辅助函数：兼容 Blender 5.0 的 F-Curve 获取器 ---
def get_all_fcurves(action):
    """
    生成器：遍历 Action 中的所有 F-Curve。
    兼容 Blender 5.0 (Slotted Actions) 和旧版本。
    """
    if hasattr(action, "fcurves"): # 旧版
        for fc in action.fcurves:
            yield fc
        return

    # Blender 5.0+ 新版结构
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, "channelbags"):
                    for channelbag in strip.channelbags:
                        for fc in channelbag.fcurves:
                            yield fc

def normalize_object(obj):
    """应用变换 (Location, Rotation, Scale)"""
    if obj.type not in {'MESH', 'ARMATURE'}:
        return
    try:
        with bpy.context.temp_override(active_object=obj, selected_editable_objects=[obj]):
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    except Exception as e:
        print(f"Failed to normalize {obj.name}: {e}")

def rename_bones(armature_obj, target_string):
    """移除骨骼名称前缀"""
    if not target_string or armature_obj.type != 'ARMATURE':
        return
    for bone in armature_obj.data.bones:
        if target_string in bone.name:
            bone.name = bone.name.replace(target_string, "")

def delete_duplicate_pattern_objects():
    """批量删除 xxxx.001 对象"""
    objects_to_delete = []
    for obj in bpy.data.objects:
        if "." in obj.name and obj.name.split(".")[-1].isdigit():
             objects_to_delete.append(obj)

    if objects_to_delete:
        count = len(objects_to_delete)
        bpy.data.batch_remove(ids=objects_to_delete)
        print(f"已批量删除 {count} 个副本对象。")

def adjust_hips_location(obj):
    """修正 Hips 位移"""
    if obj.type != 'ARMATURE' or not obj.animation_data or not obj.animation_data.action:
        return
    
    action = obj.animation_data.action
    hips_bone_name = None
    for bone in obj.data.bones:
        if "hips" in bone.name.lower():
            hips_bone_name = bone.name
            break
            
    if not hips_bone_name:
        return

    target_path = f'pose.bones["{hips_bone_name}"].location'

    # 使用兼容生成器遍历
    for fcurve in get_all_fcurves(action):
        if fcurve.data_path == target_path:
            for keyframe in fcurve.keyframe_points:
                keyframe.co[1] *= 0.01 
            fcurve.update()

class ImportMixamoFBX(bpy.types.Operator):
    bl_idname = "import.mixamo_fbx"
    bl_label = "Import Mixamo FBX"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        props = context.scene.mixamo_fix_import_properties
        folder = props.mixamo_import_folder
        target_string = props.bone_name_prefix_to_remove
        
        if not folder or not os.path.isdir(folder):
            self.report({'ERROR'}, "Invalid folder path.")
            return {'CANCELLED'}
        
        fbx_files = [f for f in os.listdir(folder) if f.lower().endswith('.fbx')]
        
        if not fbx_files:
            self.report({'WARNING'}, "No FBX files found.")
            return {'CANCELLED'}
        
        # 记录初始对象集合，用于后续清理
        # initial_objects = set(bpy.data.objects) 
        # (此处不需要记录初始，因为我们在循环内动态捕捉)

        for i, fbx_file in enumerate(fbx_files):
            fbx_path = os.path.join(folder, fbx_file)
            filename_no_ext = os.path.splitext(fbx_file)[0]
            
            # 1. 记录导入前的对象快照
            objs_before = set(bpy.data.objects)
            
            # 2. 导入
            try:
                bpy.ops.import_scene.fbx(
                    filepath=fbx_path, 
                    ignore_leaf_bones=True, 
                    automatic_bone_orientation=True,
                    anim_offset=0.0
                )
            except Exception as e:
                self.report({'ERROR'}, f"Error importing {fbx_file}: {e}")
                continue

            # 3. 计算刚导入的新对象 (差集)
            objs_after = set(bpy.data.objects)
            new_objs = list(objs_after - objs_before)
            
            self.report({'INFO'}, f"Processing {i + 1}/{len(fbx_files)}: {fbx_file}")
            
            # 4. 立即处理当前文件对应的对象
            for obj in new_objs:
                if obj.type == 'ARMATURE':
                    # 设置活动对象，以便后续操作
                    context.view_layer.objects.active = obj
                    obj.select_set(True)
                    
                    # --- 关键修复：立即重命名 Action ---
                    if obj.animation_data and obj.animation_data.action:
                        # 强制使用文件名作为动作名
                        obj.animation_data.action.name = filename_no_ext
                    
                    # 执行修复逻辑
                    rename_bones(obj, target_string)
                    normalize_object(obj)
                    adjust_hips_location(obj)

                elif obj.type == 'MESH':
                    if obj.parent and obj.parent.type == 'ARMATURE':
                        normalize_object(obj)

            # 刷新一下视图层，防止连续导入导致上下文混乱
            context.view_layer.update()

        # 5. 最后统一清理重复的空对象
        delete_duplicate_pattern_objects()
        
        self.report({'INFO'}, "Batch Import Completed.")
        return {'FINISHED'}

def register():
    bpy.utils.register_class(MixamoFixImportProperties)
    bpy.utils.register_class(MixamoFixImportPanel)
    bpy.utils.register_class(ImportMixamoFBX)
    bpy.types.Scene.mixamo_fix_import_properties = bpy.props.PointerProperty(type=MixamoFixImportProperties)

def unregister():
    if hasattr(bpy.types.Scene, "mixamo_fix_import_properties"):
        del bpy.types.Scene.mixamo_fix_import_properties
    bpy.utils.unregister_class(MixamoFixImportProperties)
    bpy.utils.unregister_class(MixamoFixImportPanel)
    bpy.utils.unregister_class(ImportMixamoFBX)

if __name__ == "__main__":
    register()