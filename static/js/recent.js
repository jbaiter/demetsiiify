var app = new Vue({
  data: {
    nextPage: 1,
    manifests: [],
    isLoading: false
  },
  template: `
    <div class="container recent-manifests">
      <div class="columns is-multiline">
        <ManifestView v-for="manifest in manifests" :manifest="manifest"
                      width="6" />
        <div v-if="nextPage" class="column is-half is-offset-3">
          <button @click="loadNext" class="button is-primary load-more"
                  :class="{'is-loading': isLoading}">
            More
          </button>
        </div>
      </div>
    </div>`,
  methods: {
    loadNext: function() {
      var vm = this;
      axios.get('/api/recent', {params: {page: vm.nextPage}})
        .then(function(response) {
          vm.nextPage = response.data.next_page;
          vm.isLoading = false;
          response.data.manifests.forEach(function(m) {
            vm.manifests.push(m);
          }, this);
        });
      vm.isLoading = true;
    }
  },
  mounted: function() {
    this.loadNext();
  }
});

app.$mount(".recent");
