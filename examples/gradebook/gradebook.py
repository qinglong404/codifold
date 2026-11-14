"""终端学生成绩管理系统。

运行：python gradebook.py
数据保存在同目录的 students.json。
"""
import json
from pathlib import Path

DATA_FILE = Path(__file__).with_name("students.json")


def load_students():
    """从磁盘读取学生列表；文件不存在时返回空列表。"""
    if not DATA_FILE.exists():
        return []
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_students(students):
    """把学生列表写回磁盘。"""
    DATA_FILE.write_text(
        json.dumps(students, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_student(students, name):
    """按姓名查找学生；找不到返回 None。"""
    for student in students:
        if student["name"] == name:
            return student
    return None


def add_student(students, name, score):
    """新增学生；姓名已存在时返回 False。"""
    if find_student(students, name) is not None:
        return False
    students.append({"name": name, "score": score})
    save_students(students)
    return True


def update_score(students, name, score):
    """修改学生成绩；找不到学生时返回 False。"""
    student = find_student(students, name)
    if student is None:
        return False
    student["score"] = score
    save_students(students)
    return True


def delete_student(students, name):
    """删除学生；找不到学生时返回 False。"""
    student = find_student(students, name)
    if student is None:
        return False
    students.remove(student)
    save_students(students)
    return True


def list_students(students):
    """按“姓名: 成绩”的格式打印全部学生。"""
    if not students:
        print("暂无学生记录")
        return
    for student in students:
        print(f'{student["name"]}: {student["score"]}')


def class_summary(students):
    """返回班级人数和平均分。"""
    if not students:
        return {"count": 0, "average": 0}
    average = sum(student["score"] for student in students) / len(students)
    return {"count": len(students), "average": round(average, 1)}


def main():
    """菜单循环：读取命令，分发到增删改查和统计。"""
    students = load_students()
    while True:
        print("1. 添加  2. 列表  3. 修改  4. 删除  5. 统计  0. 退出")
        choice = input("请选择: ").strip()
        if choice == "1":
            name = input("姓名: ").strip()
            score = float(input("成绩: "))
            print("添加成功" if add_student(students, name, score) else "学生已存在")
        elif choice == "2":
            list_students(students)
        elif choice == "3":
            name = input("姓名: ").strip()
            score = float(input("新成绩: "))
            print("修改成功" if update_score(students, name, score) else "未找到学生")
        elif choice == "4":
            name = input("姓名: ").strip()
            print("删除成功" if delete_student(students, name) else "未找到学生")
        elif choice == "5":
            print(class_summary(students))
        elif choice == "0":
            break
        else:
            print("无效选择")
    save_students(students)


if __name__ == "__main__":
    main()
