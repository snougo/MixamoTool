bl_info = {
    "name": "Transfer Root Motion (Legacy Logic Fixed)",
    "blender": (5, 0, 0),
    "category": "Animation",
    "version": (1, 8, 0),
    "author": "ChatGPT Fixed",
    "description": "Restores the specific local-rotation logic from the 4.2 version, adapted for Blender 5.0 API.",
}

import bpy
import mathutils

# --- 核心辅助函数：兼容 Blender 5.0 ---

def get_all_fcurves(action):
    """兼容 Blender 5.0 的 F-Curve 获取器"""
    if hasattr(action, "fcurves"):
        for fc in action.fcurves: yield fc
        return
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, "channelbags"):
                    for channelbag in strip.channelbags:
                        for fc in channelbag.fcurves: yield fc

def find_fcurve_compat(action, data_path, index):
    for fc in get_all_fcurves(action):
        if fc.data_path == data_path and fc.array_index == index:
            return fc
    return None

def get_or_create_fcurve(obj, action, data_path, index, group_name="Root"):
    fc = find_fcurve_compat(action, data_path, index)
    if fc: return fc
    try:
        obj.keyframe_insert(data_path=data_path, index=index, frame=0, group=group_name)
    except Exception as e:
        print(f"Error creating fcurve: {e}")
        return None
    return find_fcurve_compat(action, data_path, index)

def transfer_keyframes(source_fcurve, target_fcurve):
    if source_fcurve and target_fcurve:
        target_fcurve.keyframe_points.clear()
        for keyframe in source_fcurve.keyframe_points:
            target_fcurve.keyframe_points.insert(keyframe.co.x, keyframe.co.y, options={'FAST'})

def zero_out_keyframes(fcurve):
    if fcurve:
        for keyframe in fcurve.keyframe_points:
            keyframe.co[1] = 0

def insert_quaternion_keyframes(obj, action, bone_name, group_name, frame, quaternion):
    base_path = f'pose.bones["{bone_name}"].rotation_quaternion'
    for i in range(4):
        fcurve = get_or_create_fcurve(obj, action, base_path, i, group_name)
        if fcurve:
            fcurve.keyframe_points.insert(frame, quaternion[i], options={'FAST'})

# --- 核心逻辑：完全复刻 4.2 版本算法 ---

def transfer_motion_all_axes(hips_fcurves, root_fcurves, action):
    """XYZ 全轴转移"""
    frame_1_value = 0
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
            val = frame_1_value if frame_1_value < 0 else 0
            hips_fcurves[1].keyframe_points.insert(frame, val, options={'FAST'})
        hips_fcurves[1].update()

def transfer_motion_xz_axes(hips_fcurves, root_fcurves, action):
    """仅 XZ 轴转移"""
    for i in [0, 2]: 
        if hips_fcurves[i] and root_fcurves[i]:
            transfer_keyframes(hips_fcurves[i], root_fcurves[i])

    if root_fcurves[1]: 
        frame_start, frame_end = action.frame_range
        for frame in range(int(frame_start), int(frame_end) + 1):
            root_fcurves[1].keyframe_points.insert(frame, 0, options={'FAST'})

def fill_root_location_with_zero(root_fcurves, action):
    frame_start, frame_end = action.frame_range
    for i in range(3):
        if root_fcurves[i]:
            for frame in range(int(frame_start), int(frame_end) + 1):
                root_fcurves[i].keyframe_points.insert(frame, 0, options={'FAST'})
            root_fcurves[i].update()

def transfer_y_rotation_legacy_logic(obj, hips_bone, root_bone, action):
    """
    【复刻版逻辑】
    使用原 4.2 插件的 '局部 Y 轴提取' + '强制恢复 X/Z 分量' 逻辑。
    这对于 Mixamo 骨骼是最稳定的。
    """
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    
    original_frame = scene.frame_current
    frame_start, frame_end = map(int, action.frame_range)

    # 1. 获取第一帧的初始状态 (作为基准)
    scene.frame_set(1)
    view_layer.update() # Blender 5.0 必需
    
    # 获取 Local Rotation (注意：不是 Matrix/World)
    hips_initial_quaternion = hips_bone.rotation_quaternion.copy()

    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        view_layer.update() # 每一帧强制更新

        # 读取当前 Hips 的局部旋转
        hips_original_quaternion = hips_bone.rotation_quaternion.copy()
        
        # --- 核心复刻开始 ---
        
        # 1. 提取 Y 轴旋转 (Heading) 给 Root
        # 假设 Hips 的局部 Y 轴是垂直轴 (Mixamo 标准)
        # 仅保留 W 和 Y 分量，强制 X 和 Z 为 0
        root_new_quaternion = mathutils.Quaternion((
            hips_original_quaternion.w, 
            0, 
            hips_original_quaternion.y, 
            0
        )).normalized()

        # 2. 应用给 Root
        root_bone.rotation_quaternion = root_new_quaternion
        insert_quaternion_keyframes(obj, action, "Root", "Root", frame, root_new_quaternion)

        # 3. 计算 Hips 的新局部旋转 (逆运算)
        # Hips_New = Hips_Old * Root_Inv
        hips_new_quaternion = (hips_original_quaternion @ root_new_quaternion.inverted()).normalized()

        # 4. 【关键步骤】强制恢复 Hips 的 X 和 Z 倾斜度
        # 这就是防止“躺平”或“乱飘”的硬逻辑
        hips_new_quaternion.x = hips_initial_quaternion.x
        hips_new_quaternion.z = hips_initial_quaternion.z
        
        # --- 核心复刻结束 ---

        # 5. 应用给 Hips
        hips_bone.rotation_quaternion = hips_new_quaternion
        insert_quaternion_keyframes(obj, action, "Hips", "Hips", frame, hips_new_quaternion)

    scene.frame_set(original_frame)

# --- 操作符与 UI ---

def add_root_bone(armature, operator):
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
        armature.select_set(True)

        bpy.ops.object.mode_set(mode='OBJECT')

        if not add_root_bone(armature, self):
            return {'CANCELLED'}

        for action in bpy.data.actions:
            armature.animation_data.action = action
            context.view_layer.update()

            hips_path_base = 'pose.bones["Hips"].location'
            hips_fcurves = [find_fcurve_compat(action, hips_path_base, i) for i in range(3)]
            
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
                    # 使用复刻版逻辑
                    transfer_y_rotation_legacy_logic(armature, hips_bone, root_bone, action)
            else:
                frame_start, frame_end = action.frame_range
                root_rot_path = 'pose.bones["Root"].rotation_quaternion'
                for i in range(4):
                    fc = find_fcurve_compat(action, root_rot_path, i)
                    if fc: fc.keyframe_points.clear()
                
                for frame in range(int(frame_start), int(frame_end) + 1):
                    insert_quaternion_keyframes(armature, action, "Root", "Root", frame, (1, 0, 0, 0))

        self.report({'INFO'}, "动作转移完成 (Legacy Logic Restored)。")
        return {'FINISHED'}

class RootMotionPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_root_motion"
    bl_label = "Root Motion Transfer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Root Motion"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Target Armature:")
        layout.prop(context.scene, "target_armature", text="")
        
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

# --- 注册 ---

def register():
    bpy.utils.register_class(ApplyTransferOperator)
    bpy.utils.register_class(RootMotionPanel)
    
    bpy.types.Scene.target_armature = bpy.props.EnumProperty(
        name="Target Armature",
        description="选择目标骨架",
        items=lambda self, context: [(obj.name, obj.name, "") for obj in bpy.data.objects if obj.type == 'ARMATURE'],
    )
    
    bpy.types.Action.transfer_mode = bpy.props.EnumProperty(
        name="Transfer Mode",
        description="选择转移模式",
        items=[
            ('XZ', "Transfer XZ", "仅转移 X 和 Z 轴"),
            ('XYZ', "Transfer XYZ", "转移所有轴"),
            ('NONE', "No Transfer", "不转移位移"),
        ],
        default='XZ',
    )
    bpy.types.Action.transfer_rotation = bpy.props.BoolProperty(
        name="Transfer Rotation",
        description="是否转移 Z 轴 (Heading) 旋转",
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