bl_info = {
    "name": "Mixamo Batch Importer",
    "blender": (5, 0, 0),
    "category": "Object",
    "version": (1, 2, 2),
    "author": "ChatGPT",
    "description": (
        "Batch-import Mixamo FBX files with automatic cleanup: removes 'mixamorig:' prefix, "
        "preserves leaf bones, normalizes transforms, fixes Hips location, and deduplicates "
        "auto-suffixed objects. Ready to use with game engines out of the box."
    ),
}

import bpy
import os


# ═══════════════════════════════════════════════════════════════════
# 属性组
# ═══════════════════════════════════════════════════════════════════

class MixamoFixImportProperties(bpy.types.PropertyGroup):
    mixamo_import_folder: bpy.props.StringProperty(
        name="Mixamo FBX Folder",
        description="Folder path to import FBX files from",
        subtype='DIR_PATH',
    )
    bone_name_prefix_to_remove: bpy.props.StringProperty(
        name="Bone Name Prefix to Remove",
        description="String to be removed from bone names (e.g., 'mixamorig:')",
        default="mixamorig:",
    )


# ═══════════════════════════════════════════════════════════════════
# 面板
# ═══════════════════════════════════════════════════════════════════

class MixamoFixImportPanel(bpy.types.Panel):
    bl_label = "Mixamo Batch Import"
    bl_idname = "VIEW3D_PT_mixamo_fix_import"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mixamo Fix"
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.mixamo_fix_import_properties

        layout.prop(props, "mixamo_import_folder")
        layout.prop(props, "bone_name_prefix_to_remove")
        layout.operator("import.mixamo_fbx", text="Import & Fix Mixamo FBX", icon='IMPORT')


# ═══════════════════════════════════════════════════════════════════
# 核心辅助函数
# ═══════════════════════════════════════════════════════════════════

def get_all_fcurves(action):
    """
    生成器：遍历 Action 中的所有 F-Curve。
    兼容 Blender 5.0 (Slotted Actions) 和旧版本。
    """
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, "channelbags"):
                    for bag in strip.channelbags:
                        yield from bag.fcurves
        return

    if hasattr(action, "fcurves"):
        yield from action.fcurves


def normalize_object(obj):
    """
    应用变换 (Location, Rotation, Scale)。

    统一使用 bpy.ops.object.transform_apply，因为：
    - 对 Armature：正确处理父子关系链
    - 对 Mesh：正确经过 modifier stack（尤其是 Armature Modifier）
    """
    if obj.type not in {'MESH', 'ARMATURE'}:
        return

    mat = obj.matrix_basis
    if mat.is_identity:
        return

    if not obj.data:
        return

    try:
        with bpy.context.temp_override(
            active_object=obj,
            selected_editable_objects=[obj],
        ):
            bpy.ops.object.transform_apply(
                location=True, rotation=True, scale=True,
            )
    except Exception as e:
        print(f"Failed to normalize {obj.name}: {e}")


def rename_bones(armature_obj, target_string):
    """
    移除骨骼名称前缀，带重名冲突检测。
    """
    if not target_string or armature_obj.type != 'ARMATURE':
        return

    seen = set()
    for bone in armature_obj.data.bones:
        new_name = bone.name.replace(target_string, "")
        if new_name != bone.name:
            suffix = 1
            candidate = new_name
            while candidate in seen:
                candidate = f"{new_name}.{suffix:03d}"
                suffix += 1
            seen.add(candidate)
            bone.name = candidate
        else:
            seen.add(bone.name)


def delete_duplicate_objects(new_objs):
    """
    仅删除本次导入中产生的 *.001 / *.002 等副本对象。
    条件：副本对象的源对象（无后缀名）已存在于场景中。
    """
    if not new_objs:
        return

    to_delete = []

    for obj in new_objs:
        parts = obj.name.rsplit(".", 1)
        if len(parts) == 2 and parts[1].isdigit():
            base_name = parts[0]
            if base_name in bpy.data.objects:
                to_delete.append(obj)

    if to_delete:
        bpy.data.batch_remove(ids=to_delete)
        print(f"已删除 {len(to_delete)} 个副本对象。")


def adjust_hips_location(obj):
    """
    修正 Hips 骨骼位移（Mixamo FBX 导入后 Hips 位移偏大约 100 倍）。
    """
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

    for fcurve in get_all_fcurves(action):
        if fcurve.data_path == target_path:
            for keyframe in fcurve.keyframe_points:
                keyframe.co[1] *= 0.01
            fcurve.update()


# ═══════════════════════════════════════════════════════════════════
# 主操作符
# ═══════════════════════════════════════════════════════════════════

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

        fbx_files = sorted(
            f for f in os.listdir(folder) if f.lower().endswith('.fbx')
        )

        if not fbx_files:
            self.report({'WARNING'}, "No FBX files found.")
            return {'CANCELLED'}

        wm = context.window_manager
        wm.progress_begin(0, len(fbx_files))

        all_new_objs = []

        for i, fbx_file in enumerate(fbx_files):
            wm.progress_update(i)

            fbx_path = os.path.join(folder, fbx_file)
            filename_no_ext = os.path.splitext(fbx_file)[0]

            objs_before = set(bpy.data.objects)

            try:
                bpy.ops.import_scene.fbx(
                    filepath=fbx_path,
                    ignore_leaf_bones=False,
                    anim_offset=0.0,
                )
            except Exception as e:
                self.report({'ERROR'}, f"Error importing {fbx_file}: {e}")
                continue

            objs_after = set(bpy.data.objects)
            new_objs = list(objs_after - objs_before)
            all_new_objs.extend(new_objs)

            self.report({'INFO'}, f"Processing {i + 1}/{len(fbx_files)}: {fbx_file}")

            # 先处理 Armature
            for obj in new_objs:
                if obj.type == 'ARMATURE':
                    bpy.ops.object.select_all(action='DESELECT')
                    context.view_layer.objects.active = obj

                    if obj.animation_data and obj.animation_data.action:
                        obj.animation_data.action.name = filename_no_ext

                    rename_bones(obj, target_string)
                    normalize_object(obj)
                    adjust_hips_location(obj)

            # 再处理 Mesh
            for obj in new_objs:
                if obj.type == 'MESH':
                    if obj.parent and obj.parent.type == 'ARMATURE':
                        bpy.ops.object.select_all(action='DESELECT')
                        context.view_layer.objects.active = obj
                        normalize_object(obj)

            context.view_layer.update()

        wm.progress_end()
        delete_duplicate_objects(all_new_objs)

        self.report({'INFO'}, f"Batch import completed. {len(fbx_files)} file(s) processed.")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════
# 注册 / 注销
# ═══════════════════════════════════════════════════════════════════

def register():
    bpy.utils.register_class(MixamoFixImportProperties)
    bpy.utils.register_class(MixamoFixImportPanel)
    bpy.utils.register_class(ImportMixamoFBX)
    bpy.types.Scene.mixamo_fix_import_properties = bpy.props.PointerProperty(
        type=MixamoFixImportProperties,
    )


def unregister():
    if hasattr(bpy.types.Scene, "mixamo_fix_import_properties"):
        del bpy.types.Scene.mixamo_fix_import_properties
    bpy.utils.unregister_class(MixamoFixImportProperties)
    bpy.utils.unregister_class(MixamoFixImportPanel)
    bpy.utils.unregister_class(ImportMixamoFBX)


if __name__ == "__main__":
    register()