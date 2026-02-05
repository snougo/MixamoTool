bl_info = {
    "name": "Action Auto Looper (Blender 5.0 Fix)",
    "author": "YourName",
    "version": (1, 2),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Anima",
    "description": "Auto-match action slot, frame range and loop play",
    "category": "Animation",
}

import bpy

# ------------------------------------------------------------------------
#    核心逻辑 (Core Logic)
# ------------------------------------------------------------------------

def assign_action_robust(obj, action):
    """
    适配 Blender 5.0 的动作应用逻辑。
    """
    if not obj.animation_data:
        obj.animation_data_create()
    
    adt = obj.animation_data
    adt.action = action
    
    # Blender 5.0 Slotted Action 处理
    if hasattr(action, "slots") and len(action.slots) > 0:
        # 检查 adt 是否有 action_slot 属性 (5.0 API)
        if hasattr(adt, "action_slot"):
            needs_assign = True
            
            # 检查当前 slot 是否有效且属于当前 action
            if adt.action_slot is not None:
                # 遍历 action 的 slots 看当前 slot 是否在其中
                for s in action.slots:
                    if s == adt.action_slot:
                        needs_assign = False
                        break
            
            # 如果需要重新分配 (即当前 slot 无效或不属于此 action)
            if needs_assign:
                try:
                    adt.action_slot = action.slots[0]
                    # print(f"Assigned slot: {action.slots[0].name}")
                except Exception as e:
                    print(f"Could not assign slot: {e}")

def set_frame_range_from_action(scene, action):
    # Blender 5.0 依然兼容 frame_range
    start, end = action.frame_range
    scene.frame_start = int(start)
    scene.frame_end = int(end)
    scene.frame_current = int(start)

# ------------------------------------------------------------------------
#    数据属性 (Data Properties)
# ------------------------------------------------------------------------

class AAL_Properties(bpy.types.PropertyGroup):
    target_action: bpy.props.PointerProperty(
        name="Target Action",
        type=bpy.types.Action,
        description="Select the action to play"
    )

# ------------------------------------------------------------------------
#    操作符 (Operator)
# ------------------------------------------------------------------------

class AAL_OT_PlayLoop(bpy.types.Operator):
    """Apply action, set frame range and play"""
    bl_idname = "aal.play_loop"
    bl_label = "Play Loop"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.aal_props
        return context.active_object is not None and props.target_action is not None

    def execute(self, context):
        obj = context.active_object
        props = context.scene.aal_props
        action = props.target_action
        scene = context.scene

        # 1. 应用动作 (修复版)
        assign_action_robust(obj, action)

        # 2. 设置时间轴范围
        set_frame_range_from_action(scene, action)

        # 3. 播放控制
        if not context.screen.is_animation_playing:
            bpy.ops.screen.animation_play()

        self.report({'INFO'}, f"Looping: {action.name}")
        return {'FINISHED'}

# ------------------------------------------------------------------------
#    面板 (Panel)
# ------------------------------------------------------------------------

class AAL_PT_MainPanel(bpy.types.Panel):
    bl_label = "Action Looper 5.0"
    bl_idname = "AAL_PT_MainPanel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Anima'

    def draw(self, context):
        layout = self.layout
        props = context.scene.aal_props 
        obj = context.active_object

        if not obj:
            layout.label(text="Select Object", icon='ERROR')
            return

        col = layout.column(align=True)
        col.template_ID(props, "target_action", new="action.new", open="action.open")

        row = layout.row()
        row.scale_y = 1.5
        row.operator("aal.play_loop", icon='PLAY', text="Match & Loop")

# ------------------------------------------------------------------------
#    注册 (Registration)
# ------------------------------------------------------------------------

classes = (
    AAL_Properties,
    AAL_OT_PlayLoop,
    AAL_PT_MainPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.aal_props = bpy.props.PointerProperty(type=AAL_Properties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.aal_props

if __name__ == "__main__":
    register()