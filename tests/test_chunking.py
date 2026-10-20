from dataclasses import replace


def test_sentence_chunks_and_links():
    from app.knowledge.chunking import split_markdown
    chunks=split_markdown("p","# 售后\n## 退货\n第一句话。第二句话。第三句话。",max_chars=12,overlap=6)
    assert len(chunks)>=2
    assert all(c.answer.endswith("。") for c in chunks)
    assert chunks[0].category=="售后"
    assert chunks[0].questions==["退货"]
    assert chunks[0].next_chunk_id==chunks[1].id
    assert chunks[1].prev_chunk_id==chunks[0].id


def test_table_header_is_copied():
    from app.knowledge.chunking import split_markdown
    text="# 商品\n## 参数\n|名称|说明|\n|---|---|\n"+"".join("|项目"+str(i)+"|说明内容|\n" for i in range(8))
    chunks=split_markdown("table",text,max_chars=58,overlap=0)
    assert len(chunks)>1
    assert all(c.answer.startswith("|名称|说明|\n|---|---|") for c in chunks)
    assert all(c.content_type=="table" for c in chunks)


def test_metadata_never_enters_embedding_text():
    from app.knowledge.chunking import split_markdown,embedding_text
    chunk=split_markdown("p","# 售后\n## 政策\n必须在7天内申请。")[0]
    other=replace(chunk,section_path="绝不能进入向量",is_key_clause=False,next_chunk_id="secret")
    assert embedding_text(chunk)==embedding_text(other)
    assert "绝不能进入向量" not in embedding_text(other)


def test_fenced_heading_is_not_a_section():
    from app.knowledge.chunking import split_markdown
    fence=chr(96)*3
    chunks=split_markdown("f","# 手册\n"+fence+"\n# 伪标题\n"+fence+"\n说明。")
    assert len(chunks)==1 and chunks[0].section_path=="手册"


def test_ids_are_repeatable_and_long_sentence_not_cut():
    from app.knowledge.chunking import split_markdown
    text="# 标题\n"+"长句"*100+"。"
    a=split_markdown("s",text,max_chars=20)
    b=split_markdown("s",text,max_chars=20)
    assert a[0].id==b[0].id
    assert a[0].answer=="长句"*100+"。"


def test_multisentence_list_item_is_atomic():
    from app.knowledge.chunking import split_markdown
    text='# 售后\n## 注意\n- 第一项要拍照片。还要保留包装。\n- 第二项联系人工。然后提交申请。'
    chunks=split_markdown('list',text,max_chars=10,overlap=0)
    assert any('第一项要拍照片。还要保留包装。' in c.answer for c in chunks)
    assert any('第二项联系人工。然后提交申请。' in c.answer for c in chunks)
