package com.digitalcs.mcp.vector;

import com.huaban.analysis.jieba.JiebaSegmenter;
import com.huaban.analysis.jieba.SegToken;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 中文 sparse 向量化：jieba 切词 → 词频(TF) 稀疏向量，供 Qdrant 关键词(BM25)通道使用。
 * token 经稳定哈希映射为 uint32 维度下标，值取原始词频；IDF 权重交由 Qdrant 服务端
 * （sparse 配置 modifier=IDF）计算。哈希极小概率碰撞，对召回影响可忽略。
 */
@Component
public class SparseVectorizer {

    /** JiebaSegmenter 分词无共享可变状态，线程安全，全局复用一个实例。 */
    private final JiebaSegmenter segmenter = new JiebaSegmenter();

    /** 稀疏向量：indices 与 values 等长且一一对应，顺序无要求。 */
    public record Sparse(List<Integer> indices, List<Float> values) {
        public boolean isEmpty() {
            return indices.isEmpty();
        }
    }

    /** 切词：jieba 搜索模式 + 小写归一，过滤空白与纯标点/符号 token。 */
    public List<String> tokenize(String text) {
        List<String> tokens = new ArrayList<>();
        if (!StringUtils.hasText(text)) {
            return tokens;
        }
        for (SegToken t : segmenter.process(text, JiebaSegmenter.SegMode.SEARCH)) {
            String w = t.word.trim().toLowerCase();
            if (w.isEmpty() || isPunctuation(w)) {
                continue;
            }
            tokens.add(w);
        }
        return tokens;
    }

    /** 文本 → TF 稀疏向量：同一 token（同下标）词频累加。 */
    public Sparse toSparse(String text) {
        Map<Integer, Float> tf = new LinkedHashMap<>();
        for (String token : tokenize(text)) {
            tf.merge(hashIndex(token), 1f, Float::sum);
        }
        List<Integer> indices = new ArrayList<>(tf.size());
        List<Float> values = new ArrayList<>(tf.size());
        tf.forEach((idx, v) -> {
            indices.add(idx);
            values.add(v);
        });
        return new Sparse(indices, values);
    }

    /** token 稳定哈希为非负 31 位下标（落在 uint32 范围内）。 */
    private int hashIndex(String token) {
        return token.hashCode() & 0x7fffffff;
    }

    /** 判断 token 是否全为标点/符号（无字母数字汉字等有效字符）。 */
    private boolean isPunctuation(String w) {
        for (int i = 0; i < w.length(); i++) {
            if (Character.isLetterOrDigit(w.charAt(i))) {
                return false;
            }
        }
        return true;
    }
}
