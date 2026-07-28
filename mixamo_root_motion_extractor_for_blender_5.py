bl_info = {
    "name": "Mixamo Root Motion Extractor",
    "blender": (5, 0, 0),
    "category": "Animation",
    "version": (1, 9, 1),
    "author": "ChatGPT",
    "description": (
        "Extracts locomotion (translation and Y-axis heading rotation) from the Hips bone "
        "into a dedicated Root bone, making Mixamo animations compatible with game engines "
        "that require explicit root motion."
    ),
}

import bpy
import mathutils


# ═══════════════════════════════════════════════════════════════════
# 核心辅助函数 — Blender 5.0 兼容层
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


def build_fcurve_index(action):
    """
    预先构建 F-Curve 查找字典，避免逐帧循环中反复线性扫描。
    返回 {(data_path, array_index): fcurve}
    """
    index = {}
    for fc in get_all_fcurves(action):
        index[(fc.data_path, fc.array_index)] = fc
    return index


def find_fcurve_compat(action, data_path, index, fc_index=None):
    """
    查找指定 F-Curve。若传入 fc_index 则走 O(1) 字典查找。
    """
    if fc_index is not None:
        return fc_index.get((data_path, index))
    for fc in get_all_fcurves(action):
        if fc.data_path == data_path and fc.array_index == index:
            return fc
    return None


def get_or_create_fcurve(obj, action, data_path, index, group_name="Root", fc_index=None):
    """
    获取或创建 F-Curve。若传入 fc_index 会自动同步更新。
    """
    fc = find_fcurve_compat(action, data_path, index, fc_index)
    if fc:
        return fc
    try:
        obj.keyframe_insert(data_path=data_path, index=index, frame=0, group=group_name)
    except Exception as e:
        print(f"Error creating fcurve: {e}")
        return None
    fc = find_fcurve_compat(action, data_path, index)
    if fc and fc_index is not None:
        fc_index[(data_path, index)] = fc
    return fc


def insert_keyframe_safe(fcurve, frame, value):
    """
    插入关键帧，若同帧已存在则先删除旧键，防止 F-Curve 膨胀。
    兼容 Blender 5.2：不依赖 find(frame)，使用迭代定位。
    """
    if fcurve is None:
        return
    # 查找并删除同帧的旧键（list() 避免迭代中修改集合）
    for kp in list(fcurve.keyframe_points):
        if abs(kp.co.x - frame) < 1e-4:
            fcurve.keyframe_points.remove(kp)
            break
    fcurve.keyframe_points.insert(frame, value, options={'FAST'})


def transfer_keyframes(source_fcurve, target_fcurve):
    """将源 F-Curve 的所有关键帧复制到目标 F-Curve（先清空目标）。"""
    if source_fcurve and target_fcurve:
        target_fcurve.keyframe_points.clear()
        for keyframe in source_fcurve.keyframe_points:
            insert_keyframe_safe(target_fcurve, keyframe.co.x, keyframe.co.y)


def zero_out_keyframes(fcurve):
    """将 F-Curve 所有关键帧的 Y 值置零。"""
    if fcurve:
        for keyframe in fcurve.keyframe_points:
            keyframe.co[1] = 0.0
        fcurve.update()


def insert_quaternion_keyframes(obj, action, bone_name, group_name, frame, quaternion, fc_index=None):
    """
    为指定骨骼的旋转四元数插入一帧关键帧。
    """
    base_path = f'pose.bones["{bone_name}"].rotation_quaternion'
    for i in range(4):
        fc = get_or_create_fcurve(obj, action, base_path, i, group_name, fc_index)
        insert_keyframe_safe(fc, frame, quaternion[i])


# ═══════════════════════════════════════════════════════════════════
# 位移转移
# ═══════════════════════════════════════════════════════════════════

def transfer_motion_all_axes(hips_fcurves, root_fcurves, action):
    """XYZ 全轴转移（含 Y 轴基准修正）。"""
    frame_1_value = 0.0
    if hips_fcurves[1]:
        frame_1_value = hips_fcurves[1].evaluate(1)

    if hips_fcurves[1] and frame_1_value < 0:
        for keyframe in hips_fcurves[1].keyframe_points:
            keyframe.co[1] -= frame_1_value
        hips_fcurves[1].update()

    for i in range(3):
        if hips_fcurves[i] and root_fcurves[i]:
            transfer_keyframes(hips_fcurves[i], root_fcurves[i])

    if hips_fcurves[1]:
        frame_start, frame_end = action.frame_range
        for frame in range(int(frame_start), int(frame_end) + 1):
            val = frame_1_value if frame_1_value < 0 else 0.0
            insert_keyframe_safe(hips_fcurves[1], frame, val)
        hips_fcurves[1].update()


def transfer_motion_xz_axes(hips_fcurves, root_fcurves, action):
    """仅 XZ 轴转移，Y 轴填充 0。"""
    for i in [0, 2]:
        if hips_fcurves[i] and root_fcurves[i]:
            transfer_keyframes(hips_fcurves[i], root_fcurves[i])

    if root_fcurves[1]:
        frame_start, frame_end = action.frame_range
        for frame in range(int(frame_start), int(frame_end) + 1):
            insert_keyframe_safe(root_fcurves[1], frame, 0.0)
        root_fcurves[1].update()


def fill_root_location_with_zero(root_fcurves, action):
    """Root 位置全部填 0（No Transfer 模式）。"""
    frame_start, frame_end = action.frame_range
    for i in range(3):
        if root_fcurves[i]:
            for frame in range(int(frame_start), int(frame_end) + 1):
                insert_keyframe_safe(root_fcurves[i], frame, 0.0)
            root_fcurves[i].update()


# ═══════════════════════════════════════════════════════════════════
# 旋转转移（复刻 4.2 局部 Y 轴提取逻辑）
# ═══════════════════════════════════════════════════════════════════

def transfer_y_rotation_legacy_logic(obj, hips_bone, root_bone, action):
    """
    使用原 4.2 插件的「局部 Y 轴提取」+「强制恢复 X/Z 分量」逻辑。
    这对 Mixamo 骨骼（Y-up）是最稳定的。
    """
    scene = bpy.context.scene
    wm = bpy.context.window_manager

    original_frame = scene.frame_current
    frame_start, frame_end = map(int, action.frame_range)
    total_frames = frame_end - frame_start + 1

    fc_index = build_fcurve_index(action)

    try:
        wm.progress_begin(0, total_frames)

        scene.frame_set(1)
        hips_initial_quaternion = hips_bone.rotation_quaternion.copy()

        for i, frame in enumerate(range(frame_start, frame_end + 1)):
            wm.progress_update(i)
            scene.frame_set(frame)

            hips_original_quaternion = hips_bone.rotation_quaternion.copy()

            root_new_quaternion = mathutils.Quaternion((
                hips_original_quaternion.w,
                0.0,
                hips_original_quaternion.y,
                0.0,
            )).normalized()

            root_bone.rotation_quaternion = root_new_quaternion
            insert_quaternion_keyframes(obj, action, "Root", "Root", frame, root_new_quaternion, fc_index)

            hips_new_quaternion = (
                hips_original_quaternion @ root_new_quaternion.inverted()
            ).normalized()

            hips_new_quaternion.x = hips_initial_quaternion.x
            hips_new_quaternion.z = hips_initial_quaternion.z

            hips_bone.rotation_quaternion = hips_new_quaternion
            insert_quaternion_keyframes(obj, action, "Hips", "Hips", frame, hips_new_quaternion, fc_index)

    finally:
        wm.progress_end()
        scene.frame_set(original_frame)


# ═══════════════════════════════════════════════════════════════════
# Root 骨骼创建
# ═══════════════════════════════════════════════════════════════════

def add_root_bone(armature, operator):
    """在骨架中创建 Root 骨骼，并将 Hips 设为 Root 的子级。"""
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='EDIT')

    if "Root" in armature.data.edit_bones:
        operator.report({'INFO'}, "Root 骨骼已存在。")
        bpy.ops.object.mode_set(mode='OBJECT')
        return True

    root_bone = armature.data.edit_bones.new("Root")
    root_bone.head = (0, 0, 0)
    root_bone.tail = (0, 0, 0.4)

    hips_bone = armature.data.edit_bones.get("Hips")
    if not hips_bone:
        operator.report({'ERROR'}, "未找到名为 'Hips' 的骨骼。")
        bpy.ops.object.mode_set(mode='OBJECT')
        return False

    hips_bone.parent = root_bone
    bpy.ops.object.mode_set(mode='OBJECT')
    return True


# ═══════════════════════════════════════════════════════════════════
# 主操作符
# ═══════════════════════════════════════════════════════════════════

class ApplyTransferOperator(bpy.types.Operator):
    bl_idname = "object.apply_transfer"
    bl_label = "Apply Transfer"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        target_armature_name = context.scene.target_armature
        armature = bpy.data.objects.get(target_armature_name)

        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择有效的骨架对象。")
            return {'CANCELLED'}

        if armature.name not in context.view_layer.objects:
            self.report({'ERROR'}, "目标骨架必须在当前可见层中。")
            return {'CANCELLED'}

        context.view_layer.objects.active = armature

        bpy.ops.object.mode_set(mode='OBJECT')

        if not add_root_bone(armature, self):
            return {'CANCELLED'}

        if not armature.animation_data:
            armature.animation_data_create()

        actions = list(bpy.data.actions)
        total_actions = len(actions)
        wm = context.window_manager
        wm.progress_begin(0, total_actions)

        for idx, action in enumerate(actions):
            wm.progress_update(idx)
            armature.animation_data.action = action

            hips_path_base = 'pose.bones["Hips"].location'
            hips_fcurves = [
                find_fcurve_compat(action, hips_path_base, i) for i in range(3)
            ]

            root_path_base = 'pose.bones["Root"].location'
            root_fcurves = [None] * 3
            for i in range(3):
                root_fcurves[i] = get_or_create_fcurve(armature, action, root_path_base, i, "Root")

            mode = action.transfer_mode
            if mode == "XYZ":
                transfer_motion_all_axes(hips_fcurves, root_fcurves, action)
            elif mode == "XZ":
                transfer_motion_xz_axes(hips_fcurves, root_fcurves, action)
            elif mode == "NONE":
                fill_root_location_with_zero(root_fcurves, action)

            if mode in {"XZ", "XYZ"}:
                for i in [0, 2]:
                    if hips_fcurves[i]:
                        zero_out_keyframes(hips_fcurves[i])

            if action.transfer_rotation:
                hips_bone = armature.pose.bones.get("Hips")
                root_bone = armature.pose.bones.get("Root")
                if hips_bone and root_bone:
                    transfer_y_rotation_legacy_logic(armature, hips_bone, root_bone, action)
            else:
                frame_start, frame_end = action.frame_range
                root_rot_path = 'pose.bones["Root"].rotation_quaternion'
                for i in range(4):
                    fc = find_fcurve_compat(action, root_rot_path, i)
                    if fc:
                        fc.keyframe_points.clear()
                for frame in range(int(frame_start), int(frame_end) + 1):
                    insert_quaternion_keyframes(armature, action, "Root", "Root", frame, (1, 0, 0, 0))

        wm.progress_end()
        self.report({'INFO'}, "动作转移完成 (Legacy Logic Restored)。")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════
# 面板
# ═══════════════════════════════════════════════════════════════════

class RootMotionPanel(bpy.types.Panel):
    bl_label = "Root Motion Extractor"
    bl_idname = "OBJECT_PT_root_motion"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Root Motion"
    
    def draw(self, context):
        layout = self.layout

        layout.label(text="Target Armature:")
        layout.prop_search(context.scene, "target_armature", bpy.data, "objects", text="")

        layout.separator()
        layout.label(text="Actions Settings:")

        actions = bpy.data.actions
        if not actions:
            layout.label(text="No Actions Found.", icon='INFO')
            return

        for action in actions:
            box = layout.box()
            row = box.row()
            row.label(text=action.name, icon='ACTION')
            col = box.column(align=True)
            col.prop(action, "transfer_mode", text="Mode")
            col.prop(action, "transfer_rotation", text="Rotation")

        layout.separator()
        layout.operator("object.apply_transfer", text="Apply Transfer", icon='POSE_HLT')


# ═══════════════════════════════════════════════════════════════════
# 注册 / 注销
# ═══════════════════════════════════════════════════════════════════

def register():
    bpy.utils.register_class(ApplyTransferOperator)
    bpy.utils.register_class(RootMotionPanel)

    bpy.types.Scene.target_armature = bpy.props.StringProperty(
        name="Target Armature",
        description="选择目标骨架",
    )

    bpy.types.Action.transfer_mode = bpy.props.EnumProperty(
        name="Transfer Mode",
        description="选择位移转移模式",
        items=[
            ('XZ', "Transfer XZ", "仅转移 X 和 Z 轴位移"),
            ('XYZ', "Transfer XYZ", "转移所有轴位移"),
            ('NONE', "No Transfer", "不转移位移"),
        ],
        default='XZ',
    )

    bpy.types.Action.transfer_rotation = bpy.props.BoolProperty(
        name="Transfer Rotation",
        description="是否转移 Y 轴 (Heading) 旋转（Mixamo Y-up 标准）",
        default=False,
    )


def unregister():
    bpy.utils.unregister_class(ApplyTransferOperator)
    bpy.utils.unregister_class(RootMotionPanel)

    if hasattr(bpy.types.Scene, "target_armature"):
        del bpy.types.Scene.target_armature
    if hasattr(bpy.types.Action, "transfer_mode"):
        del bpy.types.Action.transfer_mode
    if hasattr(bpy.types.Action, "transfer_rotation"):
        del bpy.types.Action.transfer_rotation


if __name__ == "__main__":
    register()