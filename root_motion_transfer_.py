bl_info = {
    "name": "Transfer Root Motion",
    "blender": (2, 80, 0),
    "category": "Animation",
    "version": (1, 1, 4),
    "author": "chatGPT",
    "description": "Transfers Hips motion (location and rotation) data to Root bone with user-defined options.",
}

import bpy
import mathutils

# 帮助函数：查找关键帧曲线
def find_fcurve(action, bone_name, property_name, index):
    """在动作中查找骨骼的关键帧曲线。"""
    data_path = f'pose.bones["{bone_name}"].{property_name}'
    return action.fcurves.find(data_path, index=index)

# 帮助函数：创建关键帧曲线
def create_fcurve(action, bone_name, property_name, index):
    """在动作中为骨骼创建新的关键帧曲线。"""
    data_path = f'pose.bones["{bone_name}"].{property_name}'
    return action.fcurves.new(data_path, index=index)

# 帮助函数：转移关键帧数据
def transfer_keyframes(source_fcurve, target_fcurve):
    """将关键帧数据从一个曲线转移到另一个曲线。"""
    if source_fcurve and target_fcurve:
        target_fcurve.keyframe_points.clear()
        for keyframe in source_fcurve.keyframe_points:
            target_fcurve.keyframe_points.insert(keyframe.co.x, keyframe.co.y, options={'FAST'})

# 帮助函数：将曲线所有关键帧值清零
def zero_out_keyframes(fcurve):
    """清除关键帧曲线的所有数值，将其设为0。"""
    if fcurve:
        for keyframe in fcurve.keyframe_points:
            keyframe.co[1] = 0

# 帮助函数：确保关键帧分组存在
def ensure_action_group(action, group_name):
    """确保动作中包含指定名称的关键帧分组。"""
    group = action.groups.get(group_name)
    if not group:
        group = action.groups.new(name=group_name)
    return group

# 帮助函数：插入四元数关键帧
def insert_quaternion_keyframes(bone_name, action, group_name, frame, quaternion):
    """为骨骼插入旋转四元数的关键帧。"""
    group = ensure_action_group(action, group_name)
    for i, component in enumerate(["w", "x", "y", "z"]):
        fcurve = action.fcurves.find(data_path=f"pose.bones[\"{bone_name}\"].rotation_quaternion", index=i)
        if not fcurve:
            fcurve = action.fcurves.new(data_path=f"pose.bones[\"{bone_name}\"].rotation_quaternion", index=i)
        fcurve.group = group
        fcurve.keyframe_points.insert(frame, quaternion[i], options={'FAST'})

# 位移转移逻辑：处理所有轴 (X, Y, Z)
def transfer_motion_all_axes(hips_fcurves, root_fcurves, action):
    """将 Hips 的 X、Y、Z 位移转移到 Root。"""
    frame_1_value = 0
    if hips_fcurves[1]:
        frame_1_value = hips_fcurves[1].evaluate(1)

    if hips_fcurves[1] and frame_1_value < 0:
        for keyframe in hips_fcurves[1].keyframe_points:
            keyframe.co[1] -= frame_1_value
        hips_fcurves[1].update()

    for i in range(3):
        if hips_fcurves[i]:
            transfer_keyframes(hips_fcurves[i], root_fcurves[i])

    if hips_fcurves[1]:
        frame_start, frame_end = action.frame_range
        for frame in range(int(frame_start), int(frame_end) + 1):
            if frame_1_value < 0:
                hips_fcurves[1].keyframe_points.insert(frame, frame_1_value, options={'FAST'})
            else:
                hips_fcurves[1].keyframe_points.insert(frame, 0, options={'FAST'})
        hips_fcurves[1].update()

# 位移转移逻辑：仅处理 X 和 Z 轴
def transfer_motion_xz_axes(hips_fcurves, root_fcurves, action):
    """仅转移 Hips 的 X 和 Z 位移到 Root。"""
    for i in [0, 2]:
        if hips_fcurves[i]:
            transfer_keyframes(hips_fcurves[i], root_fcurves[i])

    if root_fcurves[1]:
        frame_start, frame_end = action.frame_range
        for frame in range(int(frame_start), int(frame_end) + 1):
            root_fcurves[1].keyframe_points.insert(frame, 0, options={'FAST'})

# 动态跟踪并转移 Y 轴旋转
def transfer_y_rotation_to_root_with_tracking(hips_bone, root_bone, action):
    """动态跟踪 Hips 的旋转并将 Y 轴旋转转移到 Root。"""
    bpy.context.scene.frame_set(1)
    hips_initial_quaternion = hips_bone.rotation_quaternion.copy()

    for frame in range(int(action.frame_range[0]), int(action.frame_range[1]) + 1):
        bpy.context.scene.frame_set(frame)

        hips_original_quaternion = hips_bone.rotation_quaternion.copy()
        root_new_quaternion = mathutils.Quaternion((hips_original_quaternion.w, 0, hips_original_quaternion.y, 0))

        root_bone.rotation_quaternion = root_new_quaternion
        insert_quaternion_keyframes(root_bone.name, action, "Root", frame, root_new_quaternion)

        hips_new_quaternion = (hips_original_quaternion @ root_new_quaternion.inverted()).normalized()
        hips_new_quaternion.x = hips_initial_quaternion.x
        hips_new_quaternion.z = hips_initial_quaternion.z

        hips_bone.rotation_quaternion = hips_new_quaternion
        insert_quaternion_keyframes(hips_bone.name, action, "Hips", frame, hips_new_quaternion)

# 添加 Root 骨骼
def add_root_bone(armature, operator):
    """向骨架添加 Root 骨骼并设置 Hips 为其子级。"""
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
    operator.report({'INFO'}, "Root 骨骼已成功添加。")
    return True

# 应用转移操作
class ApplyTransferOperator(bpy.types.Operator):
    bl_idname = "object.apply_transfer"
    bl_label = "Apply Transfer"

    def execute(self, context):
        target_armature = context.scene.target_armature
        armature = bpy.data.objects.get(target_armature)

        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择有效的骨架对象。")
            return {'CANCELLED'}

        # 确保 Root 骨骼存在
        if not add_root_bone(armature, self):
            return {'CANCELLED'}

        for action in bpy.data.actions:
            armature.animation_data.action = action

            # 获取 Hips 和 Root 的 location 曲线
            hips_fcurves = [find_fcurve(action, "Hips", "location", i) for i in range(3)]
            root_fcurves = [find_fcurve(action, "Root", "location", i) for i in range(3)]

            # 确保 Root 的曲线初始化和分组
            root_motion_group = action.groups.get("Root")
            if not root_motion_group:
                root_motion_group = action.groups.new(name="Root")

            for i in range(3):  # 确保 Root 的 X, Y, Z 曲线存在
                if root_fcurves[i] is None:
                    root_fcurves[i] = create_fcurve(action, "Root", "location", i)
                root_fcurves[i].group = root_motion_group

            # 位移数据的转移
            if action.transfer_mode == "XYZ":
                transfer_motion_all_axes(hips_fcurves, root_fcurves, action)
            else:
                transfer_motion_xz_axes(hips_fcurves, root_fcurves, action)

            # 归零 Hips 的 X 和 Z 位移数据
            for i in [0, 2]:
                if hips_fcurves[i]:
                    zero_out_keyframes(hips_fcurves[i])

            # 旋转数据的转移
            if action.transfer_rotation:
                hips_bone = armature.pose.bones.get("Hips")
                root_bone = armature.pose.bones.get("Root")
                if hips_bone and root_bone:
                    transfer_y_rotation_to_root_with_tracking(hips_bone, root_bone, action)
            else:
                # 如果未选择旋转转移，则填充 Root 默认四元数
                frame_start, frame_end = action.frame_range
                for frame in range(int(frame_start), int(frame_end) + 1):
                    insert_quaternion_keyframes("Root", action, "Root", frame, mathutils.Quaternion((1, 0, 0, 0)))

        self.report({'INFO'}, "动作转移已成功完成。")
        return {'FINISHED'}

# UI 面板
class RootMotionPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_root_motion"
    bl_label = "Root Motion Transfer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Root Motion"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Select Target Armature")
        layout.prop(context.scene, "target_armature", text="")
        layout.label(text="Available Actions:")
        actions = bpy.data.actions
        if not actions:
            layout.label(text="No Actions Found.", icon='INFO')
            return

        for action in actions:
            box = layout.box()
            row = box.row()
            row.label(text=action.name, icon='ACTION')
            row.prop(action, "transfer_mode", text="")
            row.prop(action, "transfer_rotation", text="Rotation")

        layout.operator("object.apply_transfer", text="Apply Transfer")

# 注册和卸载
def register():
    bpy.utils.register_class(ApplyTransferOperator)
    bpy.utils.register_class(RootMotionPanel)
    bpy.types.Scene.target_armature = bpy.props.EnumProperty(
        name="Target Armature",
        description="Select the armature to apply Root motion.",
        items=lambda self, context: [(obj.name, obj.name, "") for obj in bpy.data.objects if obj.type == 'ARMATURE'],
    )
    bpy.types.Action.transfer_mode = bpy.props.EnumProperty(
        name="Transfer Mode",
        description="Select the transfer mode for this action",
        items=[
            ('XZ', "Transfer XZ", "Transfer X and Z axes only"),
            ('XYZ', "Transfer XYZ", "Transfer X, Y, and Z axes"),
        ],
        default='XZ',
    )
    bpy.types.Action.transfer_rotation = bpy.props.BoolProperty(
        name="Transfer Rotation",
        description="Also transfer rotation",
        default=False,
    )


def unregister():
    bpy.utils.unregister_class(ApplyTransferOperator)
    bpy.utils.unregister_class(RootMotionPanel)
    del bpy.types.Scene.target_armature
    del bpy.types.Action.transfer_mode
    del bpy.types.Action.transfer_rotation


if __name__ == "__main__":
    register()