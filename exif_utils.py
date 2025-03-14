from PIL import Image
from PIL.ExifTags import TAGS
import json
import os

def get_exif_data(image_path):
    """
    获取图片的EXIF信息
    
    参数:
        image_path: 图片文件路径
    返回:
        包含EXIF信息的字典，以及标签ID映射
    """
    try:
        image = Image.open(image_path)
        exif_data = {}
        tag_ids = {}  # 存储标签名称和ID的映射
        custom_tag_names = {}  # 存储自定义标签ID到名称的映射
        
        # 检查图片是否有EXIF信息
        if hasattr(image, '_getexif') and image._getexif():
            exif_info = image._getexif()

            print(2,exif_info)
            
            # 首先检查是否有自定义标签名称映射
            if 64999 in exif_info:
                try:
                    # 尝试解析JSON格式的自定义标签映射
                    custom_tag_names = json.loads(exif_info[64999])
                except Exception as e:
                    print(f"解析自定义标签映射时出错: {str(e)}")
            
            # 处理所有EXIF标签
            for tag_id, value in exif_info.items():
                # 跳过自定义标签映射
                if tag_id == 64999:
                    continue
                
                # 获取标签名称
                if str(tag_id) in custom_tag_names:
                    # 如果是自定义标签，使用保存的名称
                    tag_name = custom_tag_names[str(tag_id)]
                else:
                    # 否则使用标准EXIF标签名称
                    tag_name = TAGS.get(tag_id, f"Unknown-{tag_id}")
                
                # 存储标签信息
                exif_data[tag_name] = value
                tag_ids[tag_name] = tag_id
            
            return exif_data, tag_ids
        else:
            print(f"图片 {image_path} 没有EXIF信息")
            return {}, {}
            
    except Exception as e:
        print(f"读取图片 {image_path} 时出错: {str(e)}")
        return {}, {}

def get_unused_tag_id(existing_ids):
    """
    获取一个未使用的标签ID
    
    参数:
        existing_ids: 已使用的标签ID列表
    返回:
        一个未使用的标签ID
    """
    # 从65000开始分配自定义标签ID
    custom_id_start = 65000
    
    # 找到一个未使用的ID
    new_id = custom_id_start
    while new_id in existing_ids:
        new_id += 1
    
    return new_id

def modify_exif_info(image_path, custom_data=None, tags_to_delete=None):
    """
    修改图片的EXIF信息
    
    参数:
        image_path: 图片路径
        custom_data: 要添加的自定义信息字典 {标签名称: 值}
        tags_to_delete: 要删除的标签ID列表
    """
    try:
        image = Image.open(image_path)
        
        # 创建新的EXIF信息
        new_exif = image.getexif()
        
        # 获取当前所有标签ID
        existing_ids = set(new_exif.keys())
        
        # 获取标签名称到ID的映射
        exif_data, tag_ids = get_exif_data(image_path)
        
        # 获取自定义标签ID到名称的映射
        custom_tag_names = {}
        if 64999 in new_exif:
            try:
                custom_tag_names = json.loads(new_exif[64999])
            except Exception:
                pass
        
        # 删除指定的标签
        if tags_to_delete:
            for tag_id in tags_to_delete:
                try:
                    tag_id = int(tag_id)
                    if tag_id in new_exif:
                        # 获取标签名称
                        if str(tag_id) in custom_tag_names:
                            tag_name = custom_tag_names[str(tag_id)]
                            # 从自定义标签映射中删除
                            del custom_tag_names[str(tag_id)]
                        else:
                            tag_name = TAGS.get(tag_id, f"Unknown-{tag_id}")
                        
                        del new_exif[tag_id]
                        print(f"已删除标签: {tag_name} (ID: {tag_id})")
                    else:
                        print(f"未找到标签ID: {tag_id}")
                except ValueError:
                    print(f"无效的标签ID: {tag_id}，请输入数字ID")
        
        # 添加新的信息
        if custom_data:
            for tag_name, value in custom_data.items():
                # 检查是否是标准EXIF标签
                standard_tag_id = None
                for k, v in TAGS.items():
                    if v == tag_name:
                        standard_tag_id = k
                        break
                
                # 如果是标准标签
                if standard_tag_id:
                    tag_id = standard_tag_id
                # 如果是已存在的自定义标签
                elif tag_name in tag_ids:
                    tag_id = tag_ids[tag_name]
                # 如果是新的自定义标签
                else:
                    tag_id = get_unused_tag_id(existing_ids)
                    existing_ids.add(tag_id)
                    # 保存自定义标签名称
                    custom_tag_names[str(tag_id)] = tag_name
                
                # 存储值
                new_exif[tag_id] = value
                print(f"已添加标签: {tag_name} (ID: {tag_id}) = {value}")
        
        # 保存自定义标签名称映射
        if custom_tag_names:
            new_exif[64999] = json.dumps(custom_tag_names)
        elif 64999 in new_exif:
            del new_exif[64999]
        
        # 保存文件
        # 获取原文件扩展名
        base_name, ext = os.path.splitext(image_path)
        # 创建临时文件，保留原扩展名
        temp_path = f"{base_name}_temp{ext}"
        image.save(temp_path, exif=new_exif.tobytes())
        
        # 关闭原图像文件
        image.close()
        
        # 替换原文件
        os.replace(temp_path, image_path)
        print(f"EXIF信息已成功更新并覆盖原文件: {image_path}")
    
    except Exception as e:
        print(f"修改EXIF信息时出错: {str(e)}")
        raise e 