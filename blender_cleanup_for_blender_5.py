bl_info = {
    "name": "增强版数据清理 (Blender 5.0 Ready)",
    "author": "ChatGPT Fixed",
    "version": (1, 5),
    "blender": (5, 0, 0),
    "location": "View3D > UI > Tool",
    "description": "适配 Blender 5.0 的安全数据清理工具，使用 batch_remove 避免迭代器错误。",
    "category": "Object",
}

import bpy
import re
from bpy.types import Panel, Operator

class OBJECT_OT_cleanup_unused_data(Operator):
    """清理所有未使用的数据块 (适配 Blender 5.0+)"""
    bl_idname = "object.cleanup_unused_data"
    bl_label = "执行清理"
    bl_options = {'REGISTER', 'UNDO'}

    def get_visible_objects_recursive(self, context):
        """递归获取所有真正可见的对象（修复逻辑漏洞）"""
        visible_objs = set()
        
        # 强制更新视图层，确保 visible_get 返回正确值
        context.view_layer.update()

        def traverse(layer_collection):
            # 如果集合被排除或隐藏，直接跳过其子级
            if layer_collection.exclude or not layer_collection.is_visible:
                return
            
            for obj in layer_collection.collection.objects:
                if obj.visible_get():
                    visible_objs.add(obj)
            
            for child in layer_collection.children:
                traverse(child)

        traverse(context.view_layer.layer_collection)
        return visible_objs

    def collect_resources_from_node_tree(self, node_tree, used_data):
        """递归收集节点树中的资源（材质节点、几何节点、世界环境）"""
        if not node_tree: return
        
        # 避免死循环
        if node_tree in used_data['node_groups']: return
        used_data['node_groups'].add(node_tree)

        for node in node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree:
                self.collect_resources_from_node_tree(node.node_tree, used_data)
            elif node.type == 'TEX_IMAGE' and node.image:
                used_data['images'].add(node.image)
            elif node.type == 'TEX_ENVIRONMENT' and node.image:
                used_data['images'].add(node.image)

    def execute(self, context):
        report_msg = []
        
        # 1. 收集所有可见对象及其依赖
        visible_objects = self.get_visible_objects_recursive(context)
        
        used_data = {
            'meshes': set(),
            'materials': set(),
            'images': set(),
            'armatures': set(),
            'actions': set(),
            'node_groups': set(),
        }

        # 收集世界环境依赖
        if context.scene.world and context.scene.world.node_tree:
            self.collect_resources_from_node_tree(context.scene.world.node_tree, used_data)

        for obj in visible_objects:
            # 动作
            if obj.animation_data and obj.animation_data.action:
                used_data['actions'].add(obj.animation_data.action)
            
            # 网格与材质
            if obj.type == 'MESH' and obj.data:
                used_data['meshes'].add(obj.data)
                for slot in obj.material_slots:
                    if slot.material:
                        used_data['materials'].add(slot.material)
                        self.collect_resources_from_node_tree(slot.material.node_tree, used_data)
            
            # 骨架
            elif obj.type == 'ARMATURE' and obj.data:
                used_data['armatures'].add(obj.data)
            
            # 几何节点修改器依赖 (Blender 4.0+ 重要特性)
            for mod in obj.modifiers:
                if mod.type == 'NODES' and mod.node_group:
                    self.collect_resources_from_node_tree(mod.node_group, used_data)

        # 2. 核心修复：使用 list 收集要删除的 ID，最后统一 batch_remove
        # 避免在遍历时修改数据导致的跳跃漏删问题
        
        # --- 清理网格 ---
        meshes_to_remove = [m for m in bpy.data.meshes if m not in used_data['meshes'] and m.users == 0]
        if meshes_to_remove:
            bpy.data.batch_remove(ids=meshes_to_remove)
            report_msg.append(f"网格: {len(meshes_to_remove)}")

        # --- 清理材质 ---
        mats_to_remove = [m for m in bpy.data.materials if m not in used_data['materials'] and m.users == 0]
        if mats_to_remove:
            bpy.data.batch_remove(ids=mats_to_remove)
            report_msg.append(f"材质: {len(mats_to_remove)}")

        # --- 清理骨架 ---
        # 先处理重复命名的骨架 (如 Armature.001)
        duplicate_armatures = []
        armature_groups = {}
        for arm in bpy.data.armatures:
            match = re.match(r'(.*?)(?:\.\d+)?$', arm.name)
            if match:
                base = match.group(1)
                if base not in armature_groups: armature_groups[base] = []
                armature_groups[base].append(arm)
        
        for arms in armature_groups.values():
            if len(arms) > 1:
                # 保留第一个，其他的如果无用户引用则加入删除列表
                for arm in arms[1:]:
                    if arm.users == 0:
                        duplicate_armatures.append(arm)
        
        # 合并普通的未使用骨架
        unused_armatures = [a for a in bpy.data.armatures if a not in used_data['armatures'] and a.users == 0]
        all_armatures_to_remove = list(set(duplicate_armatures + unused_armatures))
        
        if all_armatures_to_remove:
            bpy.data.batch_remove(ids=all_armatures_to_remove)
            report_msg.append(f"骨架: {len(all_armatures_to_remove)}")

        # --- 清理动作 ---
        actions_to_remove = [a for a in bpy.data.actions if a not in used_data['actions'] and a.users == 0]
        if actions_to_remove:
            bpy.data.batch_remove(ids=actions_to_remove)
            report_msg.append(f"动作: {len(actions_to_remove)}")

        # --- 清理节点组 ---
        groups_to_remove = [g for g in bpy.data.node_groups if g not in used_data['node_groups'] and g.users == 0]
        if groups_to_remove:
            bpy.data.batch_remove(ids=groups_to_remove)
            report_msg.append(f"节点组: {len(groups_to_remove)}")
        
        # --- 清理图像 ---
        imgs_to_remove = [img for img in bpy.data.images if img not in used_data['images'] and img.users == 0]
        if imgs_to_remove:
            bpy.data.batch_remove(ids=imgs_to_remove)
            report_msg.append(f"图像: {len(imgs_to_remove)}")

        # 3. 最后运行一次官方的深度递归清理 (Orphans Purge)
        # 它可以处理那些非常隐蔽的深层依赖
        try:
            # 显式使用 context override (适配 Blender 3.2+)
            with context.temp_override(area=context.area):
                bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        except Exception:
            # 如果上下文不对（极少情况），回退到直接调用
            bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

        self.report({'INFO'}, f"清理完成: {' | '.join(report_msg) if report_msg else '未发现垃圾数据'}")
        return {'FINISHED'}

class VIEW3D_PT_cleanup_panel(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tool'
    bl_label = "数据清理 5.0"

    def draw(self, context):
        layout = self.layout
        layout.label(text="安全清理未使用数据", icon='TRASH')
        layout.operator("object.cleanup_unused_data", icon='BRUSH_DATA')

classes = (
    OBJECT_OT_cleanup_unused_data,
    VIEW3D_PT_cleanup_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()